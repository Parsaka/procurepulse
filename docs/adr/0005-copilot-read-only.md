# 5. The Process Copilot can only read, and every answer shows its SQL

**Status:** accepted

**Context.** An LLM that writes SQL against a warehouse can be talked into reading or changing what it
should not, and a number without its query cannot be audited.

**Decision.** Three layers: a read-only connection with external access off; a sqlglot check that allows one
SELECT over `marts` and `analytics` only (no file functions, no DDL/DML, no other schemas); on Snowflake, the
role `PP_COPILOT_RO` with SELECT on those two schemas only. The answer is a structured `submit_answer` call
with one number, and every query is returned with it. A 30-question eval with ground-truth SQL measures
accuracy.

**Consequences.** Questions outside the marts cannot be answered, by design. The eval needs an API key and
costs a few cents per run.
