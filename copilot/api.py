"""HTTP API for the Process Copilot.

    uvicorn copilot.api:app --port 8000
    curl -s localhost:8000/ask -H 'content-type: application/json' -d '{"question": "How many PO items had a payment block?"}'
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from copilot.agent import ask
from copilot.tools import UnsafeQuery, check_sql, run_sql

app = FastAPI(title="ProcurePulse Process Copilot", version="1.0")


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class SqlIn(BaseModel):
    sql: str = Field(min_length=6, max_length=10000)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask")
def ask_endpoint(q: Question) -> dict:
    res = ask(q.question)
    return {"answer": res.answer, "value": res.value, "unit": res.unit, "queries": res.queries,
            "steps": res.steps, "tokens": {"input": res.input_tokens, "output": res.output_tokens}}


@app.post("/sql")
def sql_endpoint(body: SqlIn) -> dict:
    """The same guarded SQL the copilot uses, for analysts who want to check an answer."""
    try:
        check_sql(body.sql)
    except UnsafeQuery as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return run_sql(body.sql)
