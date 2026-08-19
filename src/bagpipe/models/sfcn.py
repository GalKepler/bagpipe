"""SFCN (Peng et al. 2021) brain-age CNN — DESIGN.md §4.2.

Input: CAT12 `mwp1` GM density maps in MNI space (already produced by
Pillar 1 preprocessing, matching what Pillar 4 will run at inference time).
`SFCNRegressor` is sklearn-compatible (`fit`/`predict`) so it plugs straight
into `bagpipe.models.evaluate.evaluate` like every other registered model.

Simplification vs. the paper: the original SFCN predicts a soft
classification distribution over 1-year age bins and takes its expectation.
This implementation uses a plain regression head (global-average-pool ->
linear) instead — simpler, and MAE-equivalent for a first working model.
Upgrade to the soft-classification head if it measurably beats regression.
"""

from __future__ import annotations

import csv
import re
import time
from itertools import count
from pathlib import Path

import mlflow
import numpy as np
import torch
import yaml
from sklearn.model_selection import GroupShuffleSplit
from torch import nn
from torch.utils.data import DataLoader, Dataset

from bagpipe.core.config import get_path
from bagpipe.models.bias_correction import get_corrector
from bagpipe.models.evaluate import EvalResult, evaluate
from bagpipe.models.tabular import build_image_matrix

DEFAULT_CHANNELS = [32, 64, 128, 256, 256, 64]


def _remap_ukb_pretrained_state_dict(state: dict) -> dict:
    """UKB checkpoint (github.com/ha-ha-ha-han/UKBiobank_deep_pretrain) keys
    `module.feature_extractor.conv_{i}.0/1.*` -> our `blocks.{i}.0/1.*`
    (Conv3d/BatchNorm3d are sub-indices 0/1 in each block's Sequential).
    The `module.classifier.conv_6.*` 40-bin age-classification head has no
    equivalent in our 1-unit regression head and is dropped.
    """
    remapped = {}
    for key, value in state.items():
        if not key.startswith("module.feature_extractor.conv_"):
            continue
        rest = key.removeprefix("module.feature_extractor.conv_")
        block_i, tail = rest.split(".", 1)
        remapped[f"blocks.{block_i}.{tail}"] = value
    return remapped


class SFCN(nn.Module):
    """5 conv-gn-maxpool-relu blocks + 1 conv-gn-relu block + GAP + linear.

    GroupNorm, not BatchNorm3d: at batch_size=2 (forced by 8GB VRAM),
    BatchNorm's running mean/var are estimated from 2 samples per step —
    too noisy to be a useful normalizer and a likely cause of the unstable
    UKB fine-tune run (2026-08-19). GroupNorm's stats are per-sample, so
    it's invariant to batch size. Trade-off: breaks loading the UKB
    checkpoint's BatchNorm3d weights (different state-dict shape) — fine
    for now since that fine-tune is deprioritized (see sfcn.yaml note); if
    revisited, `_remap_ukb_pretrained_state_dict` needs a norm-layer skip.
    """

    def __init__(self, channel_number: list[int] = DEFAULT_CHANNELS, dropout: float = 0.5):
        super().__init__()
        blocks = []
        in_ch = 1
        for i, out_ch in enumerate(channel_number):
            is_last = i == len(channel_number) - 1
            # Last block is 1x1x1 (no further spatial reduction), matching
            # the UKB-pretrained checkpoint's conv_5 — required for
            # `pretrained_weights_path` to load, not just a style choice.
            kernel_size, padding = (1, 0) if is_last else (3, 1)
            # GroupNorm needs num_groups to divide out_ch; 8 works for the
            # real channel widths (all multiples of 32) but tests use tiny
            # channel counts, so fall back to the largest divisor <= 8.
            num_groups = next(g for g in (8, 4, 2, 1) if out_ch % g == 0)
            layer = [
                nn.Conv3d(in_ch, out_ch, kernel_size=kernel_size, padding=padding),
                nn.GroupNorm(num_groups, out_ch),
            ]
            if not is_last:
                layer += [nn.MaxPool3d(2), nn.ReLU(inplace=True)]
            else:
                layer += [nn.ReLU(inplace=True)]
            blocks.append(nn.Sequential(*layer))
            in_ch = out_ch
        self.blocks = nn.ModuleList(blocks)
        self.gap = nn.AdaptiveAvgPool3d(1)
        self.dropout = nn.Dropout3d(dropout)
        self.head = nn.Linear(channel_number[-1], 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for block in self.blocks:
            x = block(x)
        x = self.gap(x)
        x = self.dropout(x)
        x = torch.flatten(x, 1)
        return self.head(x).squeeze(-1)


def _default_transform(augment: bool = False):
    from monai.transforms import (
        Compose,
        EnsureChannelFirst,
        LoadImage,
        NormalizeIntensity,
        RandAffine,
        RandFlip,
    )

    steps = [
        LoadImage(image_only=True, dtype=np.float32),
        EnsureChannelFirst(),
        NormalizeIntensity(nonzero=True),
    ]
    if augment:
        # Train-only. L-R flip (brain is roughly bilaterally symmetric) +
        # small rotation/translation — cheap regularizer against overfitting
        # a 3D CNN on ~5k volumes. Not applied to val/test (must stay a
        # clean estimate of generalization).
        steps += [
            RandFlip(prob=0.5, spatial_axis=0),
            RandAffine(
                prob=0.5,
                rotate_range=(0.05, 0.05, 0.05),
                translate_range=(3, 3, 3),
                padding_mode="zeros",
            ),
        ]
    return Compose(steps)


class NiftiAgeDataset(Dataset):
    """Loads `mwp1` NIfTI volumes on demand via MONAI transforms (DESIGN.md §4.2)."""

    def __init__(self, paths: np.ndarray, ages: np.ndarray | None = None, transform=None):
        self.paths = paths
        self.ages = ages
        self.transform = transform or _default_transform()

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, idx: int):
        tensor = self.transform(self.paths[idx]).as_tensor()
        if self.ages is None:
            return tensor
        return tensor, torch.tensor(self.ages[idx], dtype=torch.float32)


class SFCNRegressor:
    """sklearn-compatible wrapper: `fit(paths, ages)` / `predict(paths)`."""

    def __init__(
        self,
        epochs: int = 30,
        batch_size: int = 4,
        lr: float = 1e-4,
        weight_decay: float = 1e-3,
        dropout: float = 0.5,
        channel_number: list[int] | None = None,
        num_workers: int = 4,
        val_fraction: float = 0.1,
        patience: int = 5,
        pretrained_weights_path: str | Path | None = None,
        device: str | None = None,
        random_state: int = 0,
        verbose: bool = False,
        log_dir: str | Path | None = None,
        fold_label: str | int | None = None,
    ):
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.weight_decay = weight_decay
        self.dropout = dropout
        self.channel_number = channel_number or DEFAULT_CHANNELS
        self.num_workers = num_workers
        self.val_fraction = val_fraction
        self.patience = patience
        self.pretrained_weights_path = pretrained_weights_path
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.random_state = random_state
        self.verbose = verbose
        self.log_dir = Path(log_dir) if log_dir else None
        self.fold_label = fold_label if fold_label is not None else "run"

    def _log_epoch(self, epoch: int, train_loss: float, val_mae: float | None, epoch_s: float):
        """Appends one row to `log_dir/history.csv` and redraws
        `log_dir/loss_curve.png` — a file-based "live" plot: a background
        `bag models train-sfcn` run has no notebook to draw into, so
        progress is a PNG overwritten every epoch, viewable in any image
        viewer/IDE that auto-refreshes on file change.
        """
        self.log_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.log_dir / "history.csv"
        is_new = not csv_path.exists()
        with csv_path.open("a", newline="") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(["fold", "epoch", "train_loss", "val_mae", "epoch_seconds"])
            writer.writerow([self.fold_label, epoch, train_loss, val_mae or "", epoch_s])

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd

        history = pd.read_csv(csv_path)
        fig, (ax_loss, ax_time) = plt.subplots(1, 2, figsize=(11, 4))
        for fold, group in history.groupby("fold"):
            (line,) = ax_loss.plot(
                group["epoch"], group["train_loss"], marker="o", label=f"fold {fold} train"
            )
            if group["val_mae"].notna().any():
                ax_loss.plot(
                    group["epoch"], group["val_mae"], marker="x", ls="--", color=line.get_color()
                )
        ax_loss.set_xlabel("epoch")
        ax_loss.set_ylabel("years (L1 loss / MAE)")
        ax_loss.set_title("SFCN training — solid: train loss, dashed: val MAE")
        ax_loss.legend(fontsize=8)

        for fold, group in history.groupby("fold"):
            ax_time.plot(group["epoch"], group["epoch_seconds"], marker="o", label=f"fold {fold}")
        ax_time.set_xlabel("epoch")
        ax_time.set_ylabel("seconds")
        ax_time.set_title("epoch wall-clock time (pace / ETA)")
        ax_time.legend(fontsize=8)

        fig.tight_layout()
        tmp_path = self.log_dir / ".loss_curve.png.tmp"
        fig.savefig(tmp_path, format="png", dpi=100)
        plt.close(fig)
        tmp_path.replace(self.log_dir / "loss_curve.png")  # atomic — never a half-written PNG

    def _build_model(self) -> SFCN:
        model = SFCN(channel_number=self.channel_number, dropout=self.dropout)
        if self.pretrained_weights_path:
            state = torch.load(self.pretrained_weights_path, map_location="cpu")
            state = _remap_ukb_pretrained_state_dict(state)
            missing, unexpected = model.load_state_dict(state, strict=False)
            # head.* must be missing (fresh-init regression head, expected);
            # anything else missing/unexpected means the remap silently
            # failed to load a block, which no downstream metric will flag.
            missing = [k for k in missing if not k.startswith("head.")]
            if missing or unexpected:
                raise RuntimeError(
                    f"pretrained weight load left mismatches — missing={missing} unexpected={unexpected}"
                )
        return model.to(self.device)

    def fit(self, X: np.ndarray, y: np.ndarray, callback=None) -> SFCNRegressor:
        """`callback(epoch, train_loss, val_mae)` fires after every epoch —
        `val_mae` is `None` when no validation split was carved out. Lets
        callers (e.g. a notebook) drive a live loss plot without this class
        knowing anything about plotting.
        """
        X = np.asarray(X)
        y = np.asarray(y, dtype=np.float32)
        n_val = max(1, int(len(X) * self.val_fraction)) if len(X) > 10 else 0
        if n_val:
            # Subject-grouped, not a plain random split — a subject's other
            # session landing in val while one is in train would leak
            # identity into early-stopping/checkpoint selection (DESIGN.md's
            # non-negotiable grouped-CV rule, which the outer harness enforces
            # but this inner split previously didn't). `evaluate()` doesn't
            # pass groups through `fit(X, y)`, so derive them from the
            # `sub-<id>` BIDS entity embedded in each image path.
            subject_ids = np.array([re.search(r"sub-([^/_]+)", p).group(1) for p in X])
            splitter = GroupShuffleSplit(
                n_splits=1, test_size=self.val_fraction, random_state=self.random_state
            )
            train_idx, val_idx = next(splitter.split(X, y, subject_ids))
        else:
            train_idx, val_idx = np.arange(len(X)), np.array([], dtype=int)

        train_loader = DataLoader(
            NiftiAgeDataset(X[train_idx], y[train_idx], transform=_default_transform(augment=True)),
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=self.num_workers,
        )
        val_loader = (
            DataLoader(
                NiftiAgeDataset(X[val_idx], y[val_idx]),
                batch_size=self.batch_size,
                num_workers=self.num_workers,
            )
            if n_val
            else None
        )

        self.model_ = self._build_model()
        optimizer = torch.optim.AdamW(
            self.model_.parameters(), lr=self.lr, weight_decay=self.weight_decay
        )
        loss_fn = nn.L1Loss()
        use_amp = self.device == "cuda"
        scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

        best_val_mae = float("inf")
        best_state = None
        epochs_since_improvement = 0

        for epoch in range(self.epochs):
            epoch_start = time.time()
            self.model_.train()
            batch_losses = []
            for volumes, ages in train_loader:
                volumes, ages = volumes.to(self.device), ages.to(self.device)
                optimizer.zero_grad()
                with torch.autocast(device_type=self.device, enabled=use_amp):
                    loss = loss_fn(self.model_(volumes), ages)
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
                batch_losses.append(loss.item())
            train_loss = float(np.mean(batch_losses))

            val_mae = self._eval_mae(val_loader) if val_loader is not None else None
            epoch_s = time.time() - epoch_start
            if self.verbose:
                val_str = f", val_mae={val_mae:.3f}" if val_mae is not None else ""
                print(
                    f"  fold={self.fold_label} epoch {epoch + 1}/{self.epochs}: "
                    f"train_loss={train_loss:.3f}{val_str} ({epoch_s:.1f}s)"
                )
            if self.log_dir is not None:
                self._log_epoch(epoch, train_loss, val_mae, epoch_s)
            if callback is not None:
                callback(epoch, train_loss, val_mae)

            if val_loader is None:
                continue
            if val_mae < best_val_mae:
                best_val_mae = val_mae
                best_state = {k: v.clone() for k, v in self.model_.state_dict().items()}
                epochs_since_improvement = 0
            else:
                epochs_since_improvement += 1
                if epochs_since_improvement >= self.patience:
                    break

        if best_state is not None:
            self.model_.load_state_dict(best_state)
        return self

    def _eval_mae(self, loader: DataLoader) -> float:
        self.model_.eval()
        errors = []
        with torch.no_grad(), torch.autocast(device_type=self.device, enabled=self.device == "cuda"):
            for volumes, ages in loader:
                volumes, ages = volumes.to(self.device), ages.to(self.device)
                errors.append((self.model_(volumes) - ages).abs().cpu().numpy())
        return float(np.concatenate(errors).mean())

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X)
        loader = DataLoader(
            NiftiAgeDataset(X), batch_size=self.batch_size, num_workers=self.num_workers
        )
        self.model_.eval()
        preds = []
        with torch.no_grad(), torch.autocast(device_type=self.device, enabled=self.device == "cuda"):
            for volumes in loader:
                preds.append(self.model_(volumes.to(self.device)).cpu().numpy())
        return np.concatenate(preds)


def run(config_path: Path) -> tuple[EvalResult, dict]:
    config = yaml.safe_load(Path(config_path).read_text())
    model_cfg = config.get("model", {})

    mlflow_cfg = config.get("mlflow", {})
    mlflow_dir = get_path("mlflow_dir")
    mlflow_dir.mkdir(parents=True, exist_ok=True)
    run_name = mlflow_cfg.get("run_name") or "sfcn"

    # Progress log for a long background run: history.csv + loss_curve.png,
    # rewritten every epoch, one fold label per outer-CV fold in call order.
    log_dir = mlflow_dir / "sfcn_runs" / run_name
    fold_counter = count()

    paths, y, groups = build_image_matrix(get_path("datasets_dir"))
    model_fn = lambda: SFCNRegressor(  # noqa: E731
        **model_cfg, log_dir=log_dir, fold_label=next(fold_counter)
    )

    bias_corrector = get_corrector(config.get("bias_correction", "none"))
    n_splits = config.get("n_splits", 5)

    print(f"progress log: {log_dir / 'history.csv'}, {log_dir / 'loss_curve.png'}")
    result = evaluate(model_fn, paths, y, groups, n_splits=n_splits, bias_corrector=bias_corrector)

    mlflow.set_tracking_uri(f"sqlite:///{mlflow_dir / 'mlflow.db'}")
    mlflow.set_experiment(mlflow_cfg.get("experiment", "bagpipe-baseline"))
    with mlflow.start_run(run_name=run_name):
        mlflow.log_params(
            {
                "model_type": "sfcn",
                "bias_correction": config.get("bias_correction", "none"),
                "n_splits": n_splits,
                "n_samples": len(y),
                **{f"model.{k}": v for k, v in model_cfg.items()},
            }
        )
        mlflow.log_metrics(result.metrics)
        if (log_dir / "loss_curve.png").exists():
            mlflow.log_artifact(str(log_dir / "loss_curve.png"))
        if (log_dir / "history.csv").exists():
            mlflow.log_artifact(str(log_dir / "history.csv"))

    return result, {"run_name": run_name, "n_samples": len(y), "log_dir": str(log_dir)}


if __name__ == "__main__":
    result, info = run(Path("config/models/sfcn.yaml"))
    print(f"run: {info['run_name']} ({info['n_samples']} samples)")
    for k, v in result.metrics.items():
        print(f"  {k}: {v:.3f}")
