"""Process Copilot: answers procurement questions with numbers from the warehouse.

The model never sees raw data unless it asks for it through a read-only SQL tool,
every query it runs is returned in the trace (so an analyst can audit the answer),
and it must finish by calling submit_answer with one headline number.

    python -m copilot.agent "Which vendor causes the most payment blocks?"

Needs ANTHROPIC_API_KEY. Model: PP_COPILOT_MODEL (default claude-opus-5-5).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

import anthropic

from copilot.tools import TOOLS, describe_tables, execute

MODEL = os.environ.get("PP_COPILOT_MODEL", "claude-opus-5-5")
MAX_STEPS = 12

SYSTEM = """You are the Process Copilot of ProcurePulse, a process-mining warehouse built from a real SAP
purchase-to-pay event log (BPI Challenge 2019: one large manufacturer, 4 company codes, POs created in 2018).
You answer questions from procurement and accounts-payable managers.

How to work:
- Get every number from the warehouse with run_sql. Never estimate or recall numbers.
- Check the KPI definition with get_kpi_definition before computing a KPI, so your number matches the dashboards.
- Unless the question says otherwise, use in-scope items only (marts.fct_po_item.is_in_scope).
- Aggregate in SQL. Fetch at most a few dozen rows.
- If a query fails, read the error, fix the query and retry.
- If the data cannot answer the question, say so in submit_answer with value null.
- Finish by calling submit_answer exactly once. Shares are fractions between 0 and 1, money is EUR.

Glossary: GR = goods receipt, IR = invoice receipt, 3-way match = PO, GR and invoice must agree,
2-way match = no goods receipt expected, consignment = vendor-owned stock, invoiced separately.

Tables you can query (schema.table: columns):
{tables}
"""


@dataclass
class Result:
    question: str
    answer: str | None = None
    value: float | None = None
    unit: str | None = None
    queries: list[str] = field(default_factory=list)
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    stop: str = ""


def _system() -> str:
    tables = "\n".join(f"- {t}: {', '.join(cols)}" for t, cols in describe_tables().items())
    return SYSTEM.format(tables=tables)


def ask(question: str, client: anthropic.Anthropic | None = None, model: str = MODEL) -> Result:
    client = client or anthropic.Anthropic()
    # the system prompt and tools never change, so they are cached across questions
    system = [{"type": "text", "text": _system(), "cache_control": {"type": "ephemeral"}}]
    messages: list[dict] = [{"role": "user", "content": question}]
    res = Result(question)
    for step in range(1, MAX_STEPS + 1):
        res.steps = step
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            tools=TOOLS,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=messages,
        )
        res.input_tokens += response.usage.input_tokens
        res.output_tokens += response.usage.output_tokens
        res.stop = response.stop_reason or ""
        if response.stop_reason == "refusal":
            res.answer = "The model declined this request."
            return res
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            continue
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            text = " ".join(b.text for b in response.content if b.type == "text").strip()
            if response.stop_reason == "end_turn":
                # it answered in prose: ask once more for the structured answer
                messages.append({"role": "user", "content": "Please call submit_answer with that answer."})
                res.answer = text or res.answer
                continue
            break
        results = []
        for block in tool_uses:
            if block.name == "submit_answer":
                res.answer, res.value, res.unit = block.input["answer"], block.input["value"], block.input["unit"]
                return res
            if block.name == "run_sql":
                res.queries.append(block.input["sql"])
            content, is_error = execute(block.name, block.input)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": content[:20000],
                            "is_error": is_error})
        messages.append({"role": "user", "content": results})
    return res


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    res = ask(" ".join(argv))
    print(json.dumps(res.__dict__, indent=2, default=str))
    return 0 if res.answer else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
