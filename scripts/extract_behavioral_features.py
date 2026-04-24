"""
Extract behavioral features from Hytch data for calibration.

Reads raw_hytch_trips + raw_hytch_participants from the warehouse and
produces the aggregates consumed by src.ml.calibration.

Usage:
    python -m scripts.extract_behavioral_features [--db warehouse.duckdb]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


def extract_features(db_path: str = "warehouse.duckdb") -> dict[str, Any]:
    """
    Pull trip-level features from the warehouse.

    Returns a dict with:
        carpool_elasticity   — acceptance rate × incentive amount
        temporal_patterns    — trip volume + carpool rate by hour
        trip_summary         — scalar summary statistics
    """
    conn = duckdb.connect(db_path, read_only=True)
    try:
        carpool_elasticity = conn.execute(
            """
            SELECT
                ROUND(incentive_amount, 2) AS incentive_amount,
                COUNT(*)                    AS n_trips,
                AVG(is_carpool::INT)        AS carpool_rate,
                AVG(distance_miles)         AS avg_distance,
                AVG(duration_minutes)       AS avg_duration_min
            FROM raw_hytch_trips
            GROUP BY ROUND(incentive_amount, 2)
            ORDER BY incentive_amount
            """
        ).df()

        temporal_patterns = conn.execute(
            """
            SELECT
                EXTRACT(HOUR FROM timestamp) AS hour_of_day,
                COUNT(*)                     AS trip_count,
                AVG(distance_miles)          AS avg_distance,
                AVG(is_carpool::INT)         AS carpool_rate,
                AVG(incentive_amount)        AS avg_incentive
            FROM raw_hytch_trips
            GROUP BY EXTRACT(HOUR FROM timestamp)
            ORDER BY hour_of_day
            """
        ).df()

        trip_summary = conn.execute(
            """
            SELECT
                COUNT(*)                                  AS total_trips,
                AVG(is_carpool::INT)                      AS overall_carpool_rate,
                AVG(incentive_amount)                     AS mean_incentive,
                AVG(distance_miles)                       AS mean_distance_miles,
                AVG(duration_minutes)                     AS mean_duration_min,
                AVG(n_participants)                       AS mean_participants,
                AVG(CASE WHEN is_carpool THEN incentive_amount END) AS mean_incentive_carpool,
                AVG(CASE WHEN NOT is_carpool THEN incentive_amount END) AS mean_incentive_solo
            FROM raw_hytch_trips
            """
        ).df().to_dict("records")[0]
    finally:
        conn.close()

    return {
        "carpool_elasticity": carpool_elasticity,
        "temporal_patterns": temporal_patterns,
        "trip_summary": trip_summary,
    }


def _df_to_records(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict("records")
    return obj


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="warehouse.duckdb")
    parser.add_argument(
        "--out", default=None, help="Optional path to write features as JSON"
    )
    args = parser.parse_args()

    features = extract_features(args.db)

    print("== trip_summary ==")
    for k, v in features["trip_summary"].items():
        print(f"  {k}: {v}")
    print(f"\n== carpool_elasticity ({len(features['carpool_elasticity'])} bins) ==")
    print(features["carpool_elasticity"].to_string(index=False))
    print(f"\n== temporal_patterns ({len(features['temporal_patterns'])} hours) ==")
    print(features["temporal_patterns"].to_string(index=False))

    if args.out:
        out_path = Path(args.out)
        serializable = {
            k: _df_to_records(v) for k, v in features.items()
        }
        out_path.write_text(json.dumps(serializable, indent=2, default=str))
        print(f"\nWrote features to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
