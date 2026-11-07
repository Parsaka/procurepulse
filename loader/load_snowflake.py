"""Load Parquet files into Snowflake (the "extraction" step of a real SAP project).

    python -m loader.load_snowflake raw        # data/landing/sap/<TABLE>/**  -> PROCUREPULSE.RAW.<TABLE>   (role PP_LOADER)
    python -m loader.load_snowflake analytics  # data/analytics/*.parquet     -> PROCUREPULSE.ANALYTICS.<NAME> (role PP_TRANSFORMER)

Every table is fully reloaded (CREATE OR REPLACE + COPY INTO), so a run is idempotent.
Files go through the user stage (@~), which needs no extra grants.
Column names are created in upper case so unquoted SQL (dbt, the copilot) resolves them.

Auth: key pair only. Environment:
    SNOWFLAKE_ACCOUNT        orgname-accountname
    SNOWFLAKE_USER           PP_CI
    SNOWFLAKE_PRIVATE_KEY    PEM text of the private key (unencrypted PKCS#8)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYERS = {
    "raw": dict(src=ROOT / "data" / "landing" / "sap", schema="RAW", role="PP_LOADER", nested=True),
    "analytics": dict(src=ROOT / "data" / "analytics", schema="ANALYTICS", role="PP_TRANSFORMER", nested=False),
}
FILE_FORMAT = "PP_PARQUET"


def connect(role: str, schema: str):
    import snowflake.connector
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(os.environ["SNOWFLAKE_PRIVATE_KEY"].encode(), password=None)
    der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_USER"], private_key=der,
        role=role, warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "PP_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "PROCUREPULSE"), schema=schema,
        session_parameters={"QUERY_TAG": "procurepulse-loader"},
    )


def tables(layer: dict) -> dict[str, list[Path]]:
    src: Path = layer["src"]
    if layer["nested"]:
        return {d.name.upper(): sorted(d.rglob("*.parquet")) for d in sorted(src.iterdir()) if d.is_dir()}
    return {f.stem.upper(): [f] for f in sorted(src.glob("*.parquet"))}


def load_table(cur, schema: str, table: str, files: list[Path]) -> int:
    stage_dir = f"@~/procurepulse/{schema.lower()}/{table.lower()}"
    cur.execute(f"REMOVE {stage_dir}")
    for f in files:
        # keep the partition folder (load_month=YYYY-MM) in the staged name for lineage
        sub = f.parent.name if f.parent.name.startswith("load_month=") else ""
        target = f"{stage_dir}/{sub}" if sub else stage_dir
        cur.execute(f"PUT 'file://{f.as_posix()}' {target} AUTO_COMPRESS=FALSE OVERWRITE=TRUE PARALLEL=8")
    # Build the DDL from the files' own schema, with upper-case column names
    cur.execute(f"""
        SELECT LISTAGG('"' || UPPER(COLUMN_NAME) || '" ' || TYPE, ', ') WITHIN GROUP (ORDER BY ORDER_ID)
        FROM TABLE(INFER_SCHEMA(LOCATION => '{stage_dir}', FILE_FORMAT => '{FILE_FORMAT}'))
    """)
    columns = cur.fetchone()[0]
    cur.execute(f'CREATE OR REPLACE TABLE "{table}" ({columns}, "_LOADED_FROM" VARCHAR, "_LOADED_AT" TIMESTAMP_LTZ)')
    cur.execute(f"""
        COPY INTO "{table}" FROM {stage_dir}
        FILE_FORMAT = (FORMAT_NAME = '{FILE_FORMAT}')
        MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
        INCLUDE_METADATA = ("_LOADED_FROM" = METADATA$FILENAME, "_LOADED_AT" = METADATA$START_SCAN_TIME)
        ON_ERROR = ABORT_STATEMENT
    """)
    # Count from the COPY result itself: a COUNT(*) issued right after COPY has come back stale on
    # a fresh trial account (0 rows for a table that held all 114,441 a moment later).
    return rows_loaded(cur.description, cur.fetchall())


def rows_loaded(description, result) -> int:
    """Sum the rows_loaded column of a COPY INTO result (0 when no file was processed)."""
    names = [d[0].lower() for d in description or []]
    if "rows_loaded" not in names:
        return 0
    i = names.index("rows_loaded")
    return sum(int(r[i] or 0) for r in result)


def expected_rows(files: list[Path]) -> int:
    import pyarrow.parquet as pq
    return sum(pq.ParquetFile(f).metadata.num_rows for f in files)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("layer", choices=LAYERS)
    ap.add_argument("--only", nargs="*", help="load only these tables")
    args = ap.parse_args(argv)
    layer = LAYERS[args.layer]
    plan = tables(layer)
    if args.only:
        plan = {t: f for t, f in plan.items() if t in {o.upper() for o in args.only}}
    if not plan:
        print(f"nothing to load under {layer['src']}", file=sys.stderr)
        return 1
    con = connect(layer["role"], layer["schema"])
    failures = 0
    try:
        cur = con.cursor()
        cur.execute(f"CREATE FILE FORMAT IF NOT EXISTS {FILE_FORMAT} TYPE = PARQUET BINARY_AS_TEXT = FALSE")
        for table, files in plan.items():
            loaded, expected = load_table(cur, layer["schema"], table, files), expected_rows(files)
            status = "ok" if loaded == expected else "MISMATCH"
            failures += status != "ok"
            print(f"{layer['schema']}.{table:<24} {loaded:>10,} rows  ({len(files)} files)  {status}")
    finally:
        con.close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
