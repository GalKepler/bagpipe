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

    export = sub.add_parser("export", help="Export analytical tables")
    export_sub = export.add_subparsers(dest="export_command")
    export_sub.add_parser("training-table", help="Parquet tables for model training")

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

    if args.command == "export" and args.export_command == "training-table":
        from bagpipe.db.export_training_table import export as export_training_table

        for name, s in export_training_table().items():
            print(f"{name}: {s['rows']} rows -> {s['out_path']}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
