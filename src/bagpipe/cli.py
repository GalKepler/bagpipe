"""`bag` CLI entry point. Subcommands are added as each pillar lands."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="bag", description="Brain Age Gap PIPEline")
    sub = parser.add_subparsers(dest="command")

    ingest = sub.add_parser("ingest", help="Ingest data into the shared DB")
    ingest_sub = ingest.add_subparsers(dest="ingest_command")
    ingest_sub.add_parser("cat12", help="Ingest CAT12 T1w-derived tabular outputs")
    ingest_sub.add_parser("t1w-paths", help="Register T1w NIfTI paths for DL training")
    ingest_sub.add_parser("legacy-demographics", help="Ingest pre-SNBB cohort demographics")
    ingest_sub.add_parser("events", help="Seed the events table from config/events.yaml")

    export = sub.add_parser("export", help="Export analytical tables")
    export_sub = export.add_subparsers(dest="export_command")
    export_sub.add_parser("training-table", help="Parquet tables for model training")

    models = sub.add_parser("models", help="Train/evaluate models")
    models_sub = models.add_subparsers(dest="models_command")
    train_baseline = models_sub.add_parser("train-baseline", help="Train the tabular baseline")
    train_baseline.add_argument(
        "--config", default="config/models/baseline.yaml", help="Path to baseline config YAML"
    )
    train_stacked = models_sub.add_parser(
        "train-stacked", help="Train the per-region stacked ensemble"
    )
    train_stacked.add_argument(
        "--config", default="config/models/stacked.yaml", help="Path to stacked config YAML"
    )
    train_sfcn = models_sub.add_parser("train-sfcn", help="Train the SFCN 3D CNN")
    train_sfcn.add_argument(
        "--config", default="config/models/sfcn.yaml", help="Path to SFCN config YAML"
    )
    promote = models_sub.add_parser("promote", help="Fit on full data and register as production")
    promote.add_argument("--name", required=True, choices=["stacked"], help="Registered model name")
    promote.add_argument("--config", required=True, help="Path to model config YAML")
    promote.add_argument("--version", required=True, help="Version tag, e.g. v1")

    app_cmd = sub.add_parser("app", help="Run the public BAG report web app")
    app_sub = app_cmd.add_subparsers(dest="app_command")
    serve = app_sub.add_parser("serve", help="Serve the FastAPI upload/predict app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()

    if args.command == "ingest" and args.ingest_command == "cat12":
        from bagpipe.db.ingest_cat12 import ingest as ingest_cat12

        summary = ingest_cat12()
        print(f"CAT12 ingest: {summary['rows_ingested']} rows")
        return

    if args.command == "ingest" and args.ingest_command == "t1w-paths":
        from bagpipe.db.ingest_t1w_paths import ingest as ingest_t1w_paths

        summary = ingest_t1w_paths()
        print(
            f"T1w path ingest: {summary['snbb_rows']} SNBB rows, "
            f"{summary['legacy_rows']} legacy rows"
        )
        return

    if args.command == "ingest" and args.ingest_command == "legacy-demographics":
        from bagpipe.db.ingest_legacy_demographics import ingest as ingest_legacy_demographics

        summary = ingest_legacy_demographics()
        print(f"Legacy demographics ingest: {summary['rows_ingested']} rows")
        return

    if args.command == "ingest" and args.ingest_command == "events":
        from bagpipe.db.ingest_events import ingest as ingest_events

        summary = ingest_events()
        print(f"Events ingest: {summary['rows_ingested']} rows")
        return

    if args.command == "export" and args.export_command == "training-table":
        from bagpipe.db.export_training_table import export as export_training_table

        for name, s in export_training_table().items():
            print(f"{name}: {s['rows']} rows -> {s['out_path']}")
        return

    if args.command == "models" and args.models_command == "train-baseline":
        from bagpipe.models.baseline import run as train_baseline_run

        result, info = train_baseline_run(args.config)
        print(f"run: {info['run_name']} ({len(info['region_columns'])} regions)")
        for k, v in result.metrics.items():
            print(f"  {k}: {v:.3f}")
        return

    if args.command == "models" and args.models_command == "train-stacked":
        from bagpipe.models.stacked import run as train_stacked_run

        result, info = train_stacked_run(args.config)
        print(f"run: {info['run_name']} ({info['n_regions']} regions)")
        for k, v in result.metrics.items():
            print(f"  {k}: {v:.3f}")
        return

    if args.command == "models" and args.models_command == "train-sfcn":
        from bagpipe.models.sfcn import run as train_sfcn_run

        result, info = train_sfcn_run(args.config)
        print(f"run: {info['run_name']} ({info['n_samples']} samples), log: {info['log_dir']}")
        for k, v in result.metrics.items():
            print(f"  {k}: {v:.3f}")
        return

    if args.command == "models" and args.models_command == "promote":
        from bagpipe.models.promote import promote as promote_run

        entry = promote_run(args.name, args.config, version=args.version)
        print(f"promoted model_id={entry.model_id} {entry.name} {entry.version} -> {entry.stage}")
        return

    if args.command == "app" and args.app_command == "serve":
        import uvicorn

        uvicorn.run("bagpipe.app.api:app", host=args.host, port=args.port)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
