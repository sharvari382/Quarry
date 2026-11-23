from app.models import Message
from app.services.agent import history_to_messages
from app.services.llm.openai_client import _to_openai


def test_openai_conversion_of_tool_round_trip():
    msgs = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": [{"type": "text", "text": "thinking"},
                                          {"type": "tool_use", "id": "t1", "name": "run_sql", "input": {"sql": "x"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "rows"}]},
    ]
    out = _to_openai("sys", msgs)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[2]["tool_calls"][0]["function"] == {"name": "run_sql", "arguments": '{"sql": "x"}'}
    assert out[3] == {"role": "tool", "tool_call_id": "t1", "content": "rows"}


def test_history_includes_sql_and_starts_with_user():
    h = [Message(role="assistant", content="orphan", artifacts={}),
         Message(role="user", content="q1", artifacts={}),
         Message(role="assistant", content="a1", artifacts={"sql": ["SELECT 1"]})]
    msgs = history_to_messages(h, 10)
    assert msgs[0] == {"role": "user", "content": "q1"}
    assert "SELECT 1" in msgs[1]["content"]
