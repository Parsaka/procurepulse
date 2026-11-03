"""The agent loop, with a fake API client: no network, no key."""
from types import SimpleNamespace as NS

import copilot.agent as agent


class FakeMessages:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.script.pop(0)


def tool_use(id_, name, inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


def response(blocks, stop="tool_use"):
    return NS(content=blocks, stop_reason=stop, usage=NS(input_tokens=10, output_tokens=5))


def run(script, monkeypatch, executed):
    monkeypatch.setattr(agent, "_system", lambda: "system")
    monkeypatch.setattr(agent, "execute", lambda name, args: (executed.append((name, args)) or ('{"rows": [[42]]}', False)))
    fake = FakeMessages(script)
    client = NS(beta=NS(messages=fake))
    return agent.ask("How many?", client=client), fake


def test_runs_sql_then_submits(monkeypatch):
    executed = []
    res, fake = run([
        response([tool_use("t1", "run_sql", {"sql": "select 42 from marts.dim_date"})]),
        response([tool_use("t2", "submit_answer", {"answer": "42 items", "value": 42, "unit": "items"})]),
    ], monkeypatch, executed)
    assert (res.value, res.unit, res.steps) == (42, "items", 2)
    assert res.queries == ["select 42 from marts.dim_date"]
    assert executed == [("run_sql", {"sql": "select 42 from marts.dim_date"})]
    # the tool result goes back with the matching id, after the assistant turn
    last_user = fake.calls[1]["messages"][-1]
    assert last_user["role"] == "user" and last_user["content"][0]["tool_use_id"] == "t1"
    assert fake.calls[0]["model"] == agent.MODEL and fake.calls[0]["thinking"] == {"type": "adaptive"}


def test_prose_answer_is_nudged_to_submit(monkeypatch):
    executed = []
    res, fake = run([
        response([NS(type="text", text="It is 7.")], stop="end_turn"),
        response([tool_use("t1", "submit_answer", {"answer": "7", "value": 7, "unit": "count"})]),
    ], monkeypatch, executed)
    assert res.value == 7 and executed == []
    assert "submit_answer" in fake.calls[1]["messages"][-1]["content"]


def test_refusal_stops(monkeypatch):
    res, _ = run([response([], stop="refusal")], monkeypatch, [])
    assert res.value is None and "declined" in res.answer
