"""End-to-end analysis turns with a scripted LLM: verifies the agent loop, tool
execution against real data, SSE streaming, persistence and conversation context."""
import json

from app.services.llm.base import LLMError, LLMResponse, ToolCall
from app.services.llm.fake import FakeClient


def _events(resp) -> list[dict]:
    out = []
    for block in resp.text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def _conversation(client, dataset_ids):
    r = client.post("/api/conversations", json={"dataset_ids": dataset_ids})
    assert r.status_code == 201
    return r.json()["id"]


def _final(answer="Done.", **kw):
    return LLMResponse(text="", tool_calls=[ToolCall("f", "final_answer", {"answer": answer, "reasoning": ["r"], **kw})])


def test_full_turn_with_sql_chart_and_answer(user_client, sales_dataset):
    conv = _conversation(user_client, [sales_dataset["id"]])
    sql = "SELECT region, round(sum(revenue), 2) AS revenue FROM sales GROUP BY 1 ORDER BY 2 DESC"
    FakeClient.script(
        LLMResponse(text="", tool_calls=[ToolCall("1", "run_sql", {"sql": sql, "purpose": "Revenue by region"})]),
        LLMResponse(text="", tool_calls=[ToolCall("2", "create_chart", {
            "sql": sql, "chart_type": "bar", "x": "region", "y": ["revenue"], "title": "Revenue by region"})]),
        _final("**West** generated the highest revenue.", sql=sql, follow_ups=["Show monthly trend"]),
    )
    r = user_client.post(f"/api/conversations/{conv}/ask", json={"question": "Which region generated the highest revenue?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = _events(r)
    kinds = [e["type"] for e in events]
    assert kinds == ["step", "step_end", "artifact", "step", "step_end", "artifact", "answer", "done"]
    table = events[2]["artifact"]
    assert table["type"] == "table" and table["rows"][0][0] == "West"
    chart = events[5]["artifact"]
    assert chart["chart_type"] == "bar" and chart["data"][0]["region"] == "West"
    assert events[6]["sql"] == sql and events[6]["follow_ups"] == ["Show monthly trend"]

    # The tool result the model saw contains the real numbers.
    second_call = FakeClient.calls[1]["messages"][-1]["content"][0]
    assert second_call["type"] == "tool_result" and "West" in second_call["content"]

    detail = user_client.get(f"/api/conversations/{conv}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["title"].startswith("Which region")
    assert len(detail["messages"][1]["artifacts"]["items"]) == 2


def test_conversation_context_is_sent_on_follow_up(user_client, sales_dataset):
    conv = _conversation(user_client, [sales_dataset["id"]])
    FakeClient.script(_final("West leads.", sql="SELECT 1"))
    user_client.post(f"/api/conversations/{conv}/ask", json={"question": "Top region?"})
    FakeClient.script(_final("Here is the SQL."))
    user_client.post(f"/api/conversations/{conv}/ask", json={"question": "Generate SQL for this analysis"})
    msgs = FakeClient.calls[-1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[0]["content"] == "Top region?" and "West leads." in msgs[1]["content"]


def test_tool_error_is_returned_to_model_for_self_correction(user_client, sales_dataset):
    conv = _conversation(user_client, [sales_dataset["id"]])
    FakeClient.script(
        LLMResponse(text="", tool_calls=[ToolCall("1", "run_sql", {"sql": "SELECT revnue FROM sales", "purpose": "x"})]),
        LLMResponse(text="", tool_calls=[ToolCall("2", "run_sql", {"sql": "SELECT sum(revenue) FROM sales", "purpose": "x"})]),
        _final(),
    )
    events = _events(user_client.post(f"/api/conversations/{conv}/ask", json={"question": "total?"}))
    ends = [e for e in events if e["type"] == "step_end"]
    assert ends[0]["ok"] is False and "revnue" in ends[0]["error"]
    assert ends[1]["ok"] is True
    assert FakeClient.calls[1]["messages"][-1]["content"][0]["is_error"] is True


def test_unsafe_sql_from_model_is_blocked(user_client, sales_dataset):
    conv = _conversation(user_client, [sales_dataset["id"]])
    FakeClient.script(
        LLMResponse(text="", tool_calls=[ToolCall("1", "run_sql", {"sql": "DROP TABLE sales", "purpose": "x"})]),
        _final(),
    )
    events = _events(user_client.post(f"/api/conversations/{conv}/ask", json={"question": "drop it"}))
    end = next(e for e in events if e["type"] == "step_end")
    assert end["ok"] is False and "read-only" in end["error"]


def test_anomaly_tool_end_to_end(user_client, sales_dataset):
    conv = _conversation(user_client, [sales_dataset["id"]])
    FakeClient.script(
        LLMResponse(text="", tool_calls=[ToolCall("1", "detect_anomalies", {
            "sql": "SELECT order_id, product_id, unit_price FROM sales", "value_column": "unit_price",
            "group_column": "product_id", "label_columns": ["order_id"]})]),
        _final(),
    )
    events = _events(user_client.post(f"/api/conversations/{conv}/ask", json={"question": "Detect anomalies"}))
    art = next(e["artifact"] for e in events if e["type"] == "artifact")
    assert art["type"] == "anomalies" and art["flagged"][0]["value"] == 2400.0


def test_first_question_answer_is_cached(user_client, sales_dataset):
    conv1 = _conversation(user_client, [sales_dataset["id"]])
    FakeClient.script(_final("cached answer"))
    user_client.post(f"/api/conversations/{conv1}/ask", json={"question": "Summarise the data"})
    calls_before = len(FakeClient.calls)
    conv2 = _conversation(user_client, [sales_dataset["id"]])
    events = _events(user_client.post(f"/api/conversations/{conv2}/ask", json={"question": "summarise  the DATA"}))
    answer = next(e for e in events if e["type"] == "answer")
    assert answer["answer"] == "cached answer" and answer["cached"] is True
    assert len(FakeClient.calls) == calls_before  # no LLM call


def test_llm_outage_surfaces_friendly_error(user_client, sales_dataset, monkeypatch):
    conv = _conversation(user_client, [sales_dataset["id"]])

    def boom(*a, **k):
        raise LLMError("Could not reach the AI provider.")

    monkeypatch.setattr(FakeClient, "complete", boom)
    events = _events(user_client.post(f"/api/conversations/{conv}/ask", json={"question": "q"}))
    assert events[0] == {"type": "error", "message": "Could not reach the AI provider."}
    msgs = user_client.get(f"/api/conversations/{conv}").json()["messages"]
    assert msgs[-1]["artifacts"]["failed"] is True


def test_step_limit_terminates(user_client, sales_dataset, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "llm_max_tool_steps", 2)
    conv = _conversation(user_client, [sales_dataset["id"]])
    loop = LLMResponse(text="", tool_calls=[ToolCall("x", "run_sql", {"sql": "SELECT 1", "purpose": "loop"})])
    FakeClient.script(loop, loop, loop, loop, loop)
    events = _events(user_client.post(f"/api/conversations/{conv}/ask", json={"question": "loop forever"}))
    assert "step limit" in next(e for e in events if e["type"] == "answer")["answer"]


def test_ask_without_datasets_is_rejected(user_client):
    conv = _conversation(user_client, [])
    r = user_client.post(f"/api/conversations/{conv}/ask", json={"question": "q"})
    assert r.status_code == 400


def test_offline_mode_profiles_data(user_client, sales_dataset):
    conv = _conversation(user_client, [sales_dataset["id"]])
    events = _events(user_client.post(f"/api/conversations/{conv}/ask", json={"question": "anything"}))
    assert any(e["type"] == "artifact" and e["artifact"]["type"] == "profile" for e in events)
    assert "offline mode" in next(e for e in events if e["type"] == "answer")["answer"]


def test_export_markdown(user_client, sales_dataset):
    conv = _conversation(user_client, [sales_dataset["id"]])
    sql = "SELECT region, count(*) n FROM sales GROUP BY 1"
    FakeClient.script(
        LLMResponse(text="", tool_calls=[ToolCall("1", "run_sql", {"sql": sql, "purpose": "Orders by region"})]),
        _final("Orders are spread evenly.", sql=sql, pandas_code="sales.groupby('region').size()"),
    )
    user_client.post(f"/api/conversations/{conv}/ask", json={"question": "Orders per region"})
    md = user_client.get(f"/api/conversations/{conv}/export.md").text
    assert "## Q: Orders per region" in md and "```sql" in md and "| region | n |" in md and "```python" in md


def test_multi_file_join(user_client):
    files = [("files", (n, open(f"../sample_data/{n}", "rb").read(), "text/csv")) for n in ("sales.csv", "customers.csv")]
    ids = [d["id"] for d in user_client.post("/api/datasets", files=files).json()["datasets"]]
    conv = _conversation(user_client, ids)
    sql = ("SELECT c.customer_name, round(sum(s.revenue), 2) AS revenue FROM sales s "
           "JOIN customers c USING (customer_id) GROUP BY 1 ORDER BY 2 DESC LIMIT 5")
    FakeClient.script(LLMResponse(text="", tool_calls=[ToolCall("1", "run_sql", {"sql": sql, "purpose": "Top 5"})]),
                      _final())
    events = _events(user_client.post(f"/api/conversations/{conv}/ask", json={"question": "top five customers"}))
    table = next(e["artifact"] for e in events if e["type"] == "artifact")
    assert table["row_count"] == 5 and table["columns"] == ["customer_name", "revenue"]
    assert "TABLE customers" in FakeClient.calls[0]["system"] and "TABLE sales" in FakeClient.calls[0]["system"]
