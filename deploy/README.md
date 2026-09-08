# Deploying the Pillar 4 web app

Two long-running processes, both wrapped by systemd templates in this
directory:

- **`bagpipe-api`** — FastAPI (`bag app serve`), accepts uploads, enqueues
  jobs, answers `GET /jobs/{id}` polls. Cheap, stateless, safe to restart
  anytime.
- **`bagpipe-worker`** — Huey consumer (`bag app worker`), runs the actual
  stage graph (CAT12 → predict → report → email) for one job at a time.

They're split so a slow CAT12 run never blocks new uploads or status polls.

## Install

```bash
sudo useradd -r -m -d /opt/bagpipe bagpipe
sudo -u bagpipe git clone <repo-url> /opt/bagpipe
cd /opt/bagpipe
sudo -u bagpipe uv sync
sudo -u bagpipe cp config/local.yaml.example config/local.yaml
# fill in config/local.yaml: real paths, app.smtp_*/from_address, app.turnstile_*
```

Build (or copy) `container/cat12.sif` to the path in `config/local.yaml`'s
`paths.cat12_apptainer_image` before starting the worker — see
`docs/cat12_container_spec.md`.

## systemd

The `.service` files in `deploy/systemd/` are **templates with placeholder
paths** — this repo is public and machine-specific paths never get committed
as real values (CLAUDE.md). Fill in `User`, `WorkingDirectory` and `ExecStart`
for your machine before installing.

Two deployment shapes work:

**System units** (dedicated service account, `/opt/bagpipe` checkout):

```bash
sudo cp deploy/systemd/bagpipe-api.service deploy/systemd/bagpipe-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bagpipe-api bagpipe-worker
sudo journalctl -u bagpipe-api -u bagpipe-worker -f
```

**User units** (run as the maintainer's own account, which is what a
single-workstation deployment usually wants — the worker needs the venv, the
Apptainer image, `outputs/`, and the shared database, all owned by that user):

```bash
# real, machine-specific units live here, NOT in the repo
cp deploy/systemd/*.service ~/.config/systemd/user/   # then edit paths
systemctl --user daemon-reload
systemctl --user enable --now bagpipe-api bagpipe-worker bagpipe-tunnel
journalctl --user -u bagpipe-api -u bagpipe-worker -f

# REQUIRED, or the services stop the moment you log out:
sudo loginctl enable-linger "$USER"
```

Notes for the worker unit: leave `PrivateTmp` **off** — Apptainer's
`--writable-tmpfs` and the MATLAB runtime need the real `/tmp`. Put `dcm2niix`
(FSL) and `pydeface` (venv) on the unit's `PATH`; systemd does not read your
shell profile. Use a generous `TimeoutStopSec` so a mid-flight CAT12 run gets
a chance to notice `SIGTERM` instead of being `SIGKILL`ed.

## Public ingress — Cloudflare Tunnel

`bag app serve` binds `127.0.0.1` and has **no authentication**, so it must
never sit on a public interface. This deployment fronts it with a **Cloudflare
Tunnel** rather than a local reverse proxy: the tunnel connects *outbound* to
Cloudflare, so no inbound port is open on the host and no institutional
firewall change is needed. Cloudflare terminates TLS.

There is deliberately **no nginx/caddy in this deployment** — the tunnel does
what the proxy would have done, and Cloudflare's own rate-limiting rules
replace `limit_req`. One less moving part to keep alive.

```bash
# one-time, interactive (opens a browser; pick your zone)
cloudflared tunnel login
cloudflared tunnel create bagpipe
cloudflared tunnel route dns bagpipe <your-hostname>   # writes the CNAME for you
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: bagpipe
credentials-file: /home/<user>/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: <your-hostname>
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Then run it as a third unit alongside the api and worker (`Restart=always`).

**Upload size**: with no proxy there is no `client_max_body_size`, so the cap
is enforced in-app by `app.max_upload_size_mb`. Cloudflare's free-plan
request-body limit (**100 MB**) applies first and is the real ceiling for
anything arriving through the tunnel, so keep `max_upload_size_mb` at or below
100 — otherwise Cloudflare rejects large DICOM zips at the edge with a 413 the
app never sees and cannot explain to the user. Raise both together only on a
paid plan.

**Static asset caching — a real incident (2026-09-08).** `api.py`'s
`_no_cache_static` middleware sends `Cache-Control: no-cache` on every
`/static/*` response so a JS/CSS edit at the same URL is picked up on next
load. **Cloudflare ignores this.** On the plan this tunnel runs on,
Cloudflare's default cache behavior for static file extensions (js/css/…)
overrides the origin's `Cache-Control` with its own Browser Cache TTL — this
domain sends `max-age=14400` (4h) to every visitor regardless of what the
origin says, and confirmed to also vary unpredictably *between Cloudflare
edge PoPs*: some requests got the current file, others got a version from
hours earlier, simultaneously, with no purge or redeploy in between. This
was root-caused only after several rounds of "still broken" reports that
looked exactly like app bugs (and some real ones got found and fixed along
the way) but the *last* mile turned out to be edge-cache staleness the app
has no way to see or control.

**Fix (do this on the Cloudflare dashboard, not in code):** Rules → Cache
Rules → add a rule matching `URI Path starts with /static/` → **Cache
eligibility: Bypass cache** (or, if you want static assets cached but
correct, "Respect origin" / set Edge TTL to "Use cache-control header").
Without this, a deploy that changes `src/bagpipe/app/static/**` is not
reliably live for anyone until Cloudflare's TTL expires on its own — a
service restart alone (see systemd section above) is not enough to make a
static-file change visible in production.

## Public-abuse protection

Each accepted `/predict` costs roughly an hour of wall-clock on this
workstation (`bagpipe.app.pipeline.segment`'s CAT12 run — CPU-bound MATLAB/MCR,
**not** GPU; the GPU is only used for SFCN training, which is not in the
serving path). One job runs at a time and the box is also running the cohort
reprocess, so throughput is the thing to protect — three layers, all already
wired in code, that you turn on via config:

1. **Cloudflare Turnstile** (`app.turnstile_site_key`/`turnstile_secret_key`)
   — a free, privacy-respecting CAPTCHA alternative (no user-facing puzzle in
   most cases). Sign up at [dash.cloudflare.com](https://dash.cloudflare.com)
   (no domain/DNS setup required just for Turnstile), add a Turnstile widget,
   and copy its site key + secret key into `config/local.yaml`. Until these
   are set, `/predict` skips verification entirely (logged as a warning) —
   fine for local dev, **not for a public deployment**.
2. **`app.max_queue_depth`** (default 5) — `/predict` returns `503` once
   this many jobs are already queued/running, instead of letting an
   unbounded backlog build up behind the single worker.
3. **Cloudflare rate-limiting rule** — Security -> WAF -> Rate limiting rules,
   scoped to the `/predict` path (e.g. 2 requests/hour per IP). Blocks abuse at
   Cloudflare's edge, before it costs you a request. Replaces the nginx
   `limit_req` this deployment no longer has.

None of these require an account system — the upload page at `GET /` stays
open to anyone, which is what "general public, no login" means here; they
just stop it from being a free unlimited-compute faucet.

## SMTP (sending the report email)

`app.smtp_host`/`app.smtp_port`/`app.smtp_user`/`app.smtp_password`/
`app.from_address` in `config/local.yaml` drive email delivery
(`bagpipe.app.email`). Recommended: a transactional email provider rather
than your own mail server — self-hosted SMTP has a real risk of landing in
spam with no existing sender reputation, and provider free tiers are more
than enough for this app's volume.

**[Resend](https://resend.com)** (free tier: 3,000 emails/month, no credit
card):

1. Sign up, verify a sending domain (or use their shared `onboarding@
   resend.dev` address for testing only — production should use your own
   domain for deliverability).
2. Create an API key.
3. Config:
   ```yaml
   app:
     smtp_host: smtp.resend.com
     smtp_port: 587
     smtp_user: resend          # literal string, not your account name
     smtp_password: <your Resend API key>
     from_address: reports@yourdomain.org   # must match the verified domain
   ```

Any other provider with SMTP support (Postmark, SES, Brevo, ...) works the
same way — host/port/user/password from their dashboard.

## Privacy / retention

Uploaded imaging is deleted after each job finishes unless the uploader passes
`retain_uploads=true` on `POST /predict` — the uploader's own explicit
per-upload consent, not a server-wide setting
(`bagpipe.app.queue._delete_imaging`).

"Imaging" means all four locations, and getting this list wrong is how the
promise quietly becomes false (it was, until 2026-09-03 — `{job_id}/input/`
and `run/ingest/`, both holding **raw pre-deface** T1w, were never deleted):

| path | contents |
|---|---|
| `{job_id}/input/` | the raw upload as received — **pre-deface** |
| `{job_id}/run/ingest/` | dcm2niix output / NIfTI passthrough — **pre-deface** |
| `{job_id}/run/anon/` | defaced T1w |
| `{job_id}/run/cat12/` | raw CAT12 output |

`features/`, `predict/`, `report/` and `manifest.json` are tabular/report
outputs, not imaging, and are kept so `GET /jobs/{id}` and the PDF route keep
working after cleanup. Every deletion is checked to resolve strictly inside
`paths.uploads_dir` first.

**Retention duration**: `bag app retention-sweep --max-age-days N` (default 30)
removes job directories older than the cutoff, including opted-in ones. Wrap it
with `scripts/retention_sweep.sh` on a cron — it is not installed by default:

```cron
0 4 * * * /path/to/bagpipe/scripts/retention_sweep.sh >> /path/to/bagpipe/outputs/logs/retention_sweep.log 2>&1
```

## Before trusting this in production

- CAT12 version parity is **satisfied as of 2026-08-25**: the training cohort
  moved to `source="cat12_v26"` (CAT12.cohort_2026_08), which is produced by
  the same `outputs/containers/cat12.sif` the app runs. Older warnings about a
  "CAT26.0.rc3 vs training's CAT12.9/2577" mismatch are obsolete. What is still
  owed: re-run the §6 reproducibility test (`docs/cat12_container_spec.md`,
  `bag preprocess repro-test`) after *any* container rebuild before trusting
  that image for inference.
- The promoted model must be one the app can actually serve. `FeaturesStage`
  parses volume ROIs only (`catROI_*.xml`); `bagpipe.app.surface_atlas` is
  wired into cohort *ingestion*, not the app pipeline. Promoting a config with
  surface metrics (`stacked_v26_surface.yaml`) makes every upload fail with
  `FEATURE_SCHEMA_MISMATCH` — `scripts/periodic_promote.sh` is pinned to
  `stacked_v26.yaml` for this reason.
- `GET /jobs/{id}` has no auth beyond the job ID itself — anyone who knows
  (or guesses) a job's UUID can read its prediction. UUIDv4 isn't
  practically guessable, so this is intentionally treated as a "possession
  of the link is the credential" model (same as e.g. a Google Docs share
  link), not a bug — but don't build anything that leaks job IDs (e.g. a
  public list of recent jobs) without revisiting this.
- Turnstile/`max_queue_depth`/the Cloudflare rate-limit rule (§ Public-abuse protection)
  must actually be configured, not just present in code — a fresh
  `config/local.yaml` from the example ships with Turnstile unset
  (verification skipped) until you fill in real keys.
- Single worker by design — a burst of uploads queues, it doesn't fail. CAT12
  is CPU-bound and this box also runs the cohort reprocess at concurrency 12,
  so check real free cores and RAM (each CAT12 worker wants ~6-12 GB) before
  raising `--workers`, not just the core count.
