"""Tools the Process Copilot may call. All of them are read-only.

Safety is layered: (1) the DuckDB connection is opened read-only, (2) every query is
parsed with sqlglot and must be exactly one SELECT over the marts/analytics schemas,
(3) results are capped. On Snowflake the same tools run as role PP_COPILOT_RO, which
can only SELECT from MARTS and ANALYTICS (infra/snowflake/main.tf).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import duckdb
import sqlglot
from sqlglot import exp

from analytics.common import DB_PATH

ALLOWED_SCHEMAS = {"marts", "analytics"}
MAX_ROWS = 200
KPI_FILE = Path(__file__).with_name("kpi_definitions.json")


class UnsafeQuery(ValueError):
    pass


def check_sql(sql: str) -> str:
    """Return the query if it is one read-only SELECT over allowed schemas, else raise UnsafeQuery."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise UnsafeQuery(f"could not parse SQL: {e}") from e
    if len(statements) != 1:
        raise UnsafeQuery("exactly one statement is allowed")
    stmt = statements[0]
    if not isinstance(stmt, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise UnsafeQuery("only SELECT queries are allowed")
    forbidden = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Copy)
    if any(stmt.find_all(*forbidden)):
        raise UnsafeQuery("data modification is not allowed")
    cte_names = {c.alias_or_name.lower() for c in stmt.find_all(exp.CTE)}
    for table in stmt.find_all(exp.Table):
        name = table.name.lower()
        if not table.db and name in cte_names:
            continue
        if table.db.lower() not in ALLOWED_SCHEMAS:
            raise UnsafeQuery(f"table '{table.sql()}' is outside the allowed schemas "
                              f"({', '.join(sorted(ALLOWED_SCHEMAS))}); qualify tables like marts.fct_po_item")
    for fn in stmt.find_all(exp.Anonymous):
        if fn.name.lower() in {"read_csv", "read_parquet", "read_json", "read_text", "read_blob", "glob"}:
            raise UnsafeQuery("file access is not allowed")
    if any(stmt.find_all(exp.ReadCSV, exp.ReadParquet)):
        raise UnsafeQuery("file access is not allowed")
    return sql


@lru_cache(maxsize=1)
def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("set enable_external_access = false")
    return con


def run_sql(sql: str) -> dict:
    """Execute a checked query and return columns + up to MAX_ROWS rows."""
    check_sql(sql)
    cur = _con().cursor()
    rel = cur.execute(sql)
    cols = [d[0] for d in rel.description]
    rows = rel.fetchmany(MAX_ROWS + 1)
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    return {"columns": cols, "rows": [[_jsonable(v) for v in r] for r in rows], "truncated": truncated}


def _jsonable(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (int, str, bool)) or v is None:
        return v
    return str(v)


@lru_cache(maxsize=1)
def describe_tables() -> dict:
    """Columns of every table the copilot may query."""
    rows = _con().execute("""
        select table_schema || '.' || table_name, column_name, data_type
        from information_schema.columns
        where table_schema in ('marts', 'analytics')
        order by table_schema, table_name, ordinal_position""").fetchall()
    out: dict[str, list[str]] = {}
    for table, col, typ in rows:
        out.setdefault(table, []).append(f"{col} {typ}")
    return out


def kpi_definitions() -> dict:
    return json.loads(KPI_FILE.read_text())


TOOLS = [
    {
        "name": "run_sql",
        "description": (
            "Run ONE read-only DuckDB SELECT against the ProcurePulse warehouse and get the result rows "
            f"(at most {MAX_ROWS}). Always qualify tables with their schema, e.g. marts.fct_po_item. "
            "Only the schemas marts and analytics are readable. Aggregate in SQL instead of fetching raw rows."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single SELECT statement"}},
            "required": ["sql"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "get_kpi_definition",
        "description": "Look up the official definition, SQL logic and caveats of a KPI or deviation by name "
                       "(or 'all' for the list). Use it before computing a KPI so the number matches the dashboards.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "submit_answer",
        "description": "Finish: submit the final answer. Call it exactly once, after you have the number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "Short answer in plain English for a procurement manager"},
                "value": {"type": ["number", "null"], "description": "The headline number, unrounded, as a plain number "
                                                                  "(a share as a fraction 0-1, money in EUR); null if the "
                                                                  "question has no single number"},
                "unit": {"type": "string", "description": "e.g. share, EUR, days, items, touches, count, text"},
            },
            "required": ["answer", "value", "unit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def execute(name: str, args: dict) -> tuple[str, bool]:
    """Run a tool; returns (content, is_error)."""
    try:
        if name == "run_sql":
            return json.dumps(run_sql(args["sql"])), False
        if name == "get_kpi_definition":
            defs = kpi_definitions()
            key = args["name"].strip().lower()
            if key == "all":
                return json.dumps({k: v["definition"] for k, v in defs.items()}), False
            hits = {k: v for k, v in defs.items() if key in k.lower() or key in v["definition"].lower()}
            return (json.dumps(hits) if hits else f"No KPI matches '{args['name']}'. Known: {', '.join(defs)}"), not hits
        return f"unknown tool {name}", True
    except UnsafeQuery as e:
        return f"Query rejected: {e}", True
    except duckdb.Error as e:
        return f"SQL error: {e}", True
