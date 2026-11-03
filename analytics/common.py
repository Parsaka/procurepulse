"""Shared helpers: warehouse connection and result publishing.

Analytics read the dbt marts from DuckDB and write their results back as tables
in the `analytics` schema (so BI and the copilot can query them) and as Parquet
under data/analytics (so the public app can ship them).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("PP_DUCKDB_PATH", ROOT / "data" / "procurepulse.duckdb"))
OUT_DIR = ROOT / "data" / "analytics"
DOCS_IMG = ROOT / "docs" / "img"
SEED = 20181231


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} not found - run `make build` first")
    return duckdb.connect(str(DB_PATH), read_only=read_only)


def publish(con: duckdb.DuckDBPyConnection, name: str, df: pd.DataFrame) -> None:
    """Write a result table to the warehouse and to Parquet."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con.execute("create schema if not exists analytics")
    con.register("_df", df)
    con.execute(f"create or replace table analytics.{name} as select * from _df")
    con.unregister("_df")
    df.to_parquet(OUT_DIR / f"{name}.parquet", index=False)


def save_json(name: str, obj) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.json").write_text(json.dumps(obj, indent=2, default=float))
