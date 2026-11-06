import argparse
import sys
import os
import logging
from pathlib import Path

# Ensure project root is in sys.path
_file_path = Path(__file__).resolve()
_project_dir = _file_path.parent.parent.parent
if str(_project_dir) not in sys.path:
    sys.path.insert(0, str(_project_dir))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("f1_cli")

def main():
    parser = argparse.ArgumentParser(
        description="F1 Data Ingestion Pipeline - Import official race sessions, laps, stints, and pitstops into PostgreSQL."
    )
    parser.add_argument(
        "--season",
        type=int,
        required=True,
        help="F1 Championship season year (e.g. 2023, 2024, 2025, 2026)"
    )
    parser.add_argument(
        "--round",
        type=int,
        dest="round_no",
        default=None,
        help="Optional specific round number to import (e.g. 1 for Bahrain GP)"
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="Maximum number of rounds to import when processing an entire season"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging output"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Lazy import to avoid loading heavy packages on --help
    from app.data_ingestion.importer import DatabaseImporter

    importer = DatabaseImporter()

    print(f"\n=======================================================")
    print(f"  F1 PITSTOP OPTIMIZER - DATA INGESTION PIPELINE")
    print(f"=======================================================")
    print(f"Season: {args.season}")
    if args.round_no:
        print(f"Round : {args.round_no}")
    else:
        print(f"Mode  : Entire season (max_rounds: {args.max_rounds or 'All'})")
    print(f"-------------------------------------------------------\n")

    try:
        if args.round_no is not None:
            result = importer.import_round(args.season, args.round_no)
            print(f"[SUCCESS] Round {args.season} R{args.round_no} imported successfully:")
            print(f"  - Race ID        : {result.get('race_id')}")
            print(f"  - Drivers        : {result.get('drivers_count')}")
            print(f"  - Laps Imported  : {result.get('laps_imported')}")
            print(f"  - Stints Imported: {result.get('stints_imported')}")
            print(f"  - Pit Stops      : {result.get('stops_imported')}")
            print(f"  - Materialized View Refreshed: mv_driver_championship")
        else:
            results = importer.import_season(args.season, max_rounds=args.max_rounds)
            print(f"[SUMMARY] Ingestion complete for Season {args.season}:")
            for r in results:
                st = r.get("status")
                rnd = r.get("round_no")
                if st == "completed":
                    print(f"  - Round {rnd:2d}: Laps={r.get('laps_imported'):4d}, Stints={r.get('stints_imported'):2d}, Pits={r.get('stops_imported'):2d} [OK]")
                else:
                    print(f"  - Round {rnd:2d}: FAILED ({r.get('error')})")
        print(f"\n=======================================================\n")
    except Exception as e:
        logger.error(f"Fatal error during ingestion: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
