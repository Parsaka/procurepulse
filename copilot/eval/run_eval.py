"""Score the Process Copilot against questions.yaml.

    python -m copilot.eval.run_eval              # all 30 questions (needs ANTHROPIC_API_KEY)
    python -m copilot.eval.run_eval --only q01 q05
    python -m copilot.eval.run_eval --truth-only # just compute ground truth, no API calls

A question passes when the submitted value matches the ground-truth SQL within the
tolerance (default 0.5% relative). Results go to copilot/eval/results.json and a
markdown table to copilot/eval/RESULTS.md.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import yaml

from copilot.tools import _con

HERE = Path(__file__).parent
DEFAULT_TOL = 0.005


def truth(q: dict) -> float:
    return float(_con().execute(q["sql"]).fetchone()[0])


def passes(value, expected: float, q: dict) -> bool:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    value = float(value)
    if "abs_tol" in q:
        return abs(value - expected) <= q["abs_tol"]
    tol = q.get("tol", DEFAULT_TOL)
    # accept a share given as percent (e.g. 19.9 for 0.199)
    candidates = [value, value / 100] if 0 <= expected <= 1 < value <= 100 else [value]
    return any(abs(c - expected) <= tol * max(abs(expected), 1e-9) for c in candidates)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--truth-only", action="store_true")
    args = ap.parse_args(argv)
    questions = yaml.safe_load((HERE / "questions.yaml").read_text())
    if args.only:
        questions = [q for q in questions if q["id"] in args.only]
    if args.truth_only:
        for q in questions:
            print(f"{q['id']}  {truth(q):>18,.4f}  {q['question']}")
        return 0

    from copilot.agent import MODEL, ask

    rows = []
    for q in questions:
        expected = truth(q)
        t0 = time.time()
        res = ask(q["question"])
        ok = passes(res.value, expected, q)
        rows.append({"id": q["id"], "category": q["category"], "question": q["question"], "expected": expected,
                     "value": res.value, "unit": res.unit, "pass": ok, "answer": res.answer, "queries": res.queries,
                     "steps": res.steps, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
                     "seconds": round(time.time() - t0, 1)})
        print(f"{q['id']} {'PASS' if ok else 'FAIL'}  expected {expected:,.4f}  got {res.value}  ({res.steps} steps)")
    n_pass = sum(r["pass"] for r in rows)
    by_cat: dict[str, list[bool]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r["pass"])
    summary = {"model": MODEL, "questions": len(rows), "passed": n_pass, "accuracy": n_pass / max(1, len(rows)),
               "by_category": {k: sum(v) / len(v) for k, v in by_cat.items()},
               "avg_steps": sum(r["steps"] for r in rows) / max(1, len(rows)),
               "input_tokens": sum(r["input_tokens"] for r in rows),
               "output_tokens": sum(r["output_tokens"] for r in rows)}
    (HERE / "results.json").write_text(json.dumps({"summary": summary, "results": rows}, indent=2, default=str))
    lines = [f"# Copilot eval: {n_pass}/{len(rows)} correct ({summary['accuracy']:.0%})", "",
             f"Model `{MODEL}`, average {summary['avg_steps']:.1f} model calls per question.", "",
             "| Category | Accuracy |", "|---|---|"]
    lines += [f"| {k} | {v:.0%} |" for k, v in summary["by_category"].items()]
    lines += ["", "| id | pass | expected | copilot | question |", "|---|---|---|---|---|"]
    lines += [f"| {r['id']} | {'✅' if r['pass'] else '❌'} | {r['expected']:,.4g} | {r['value']} | {r['question']} |"
              for r in rows]
    (HERE / "RESULTS.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
