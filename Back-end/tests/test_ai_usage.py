import httpx

from app.matching import OpenRouterLLM


def _llm(handler):
    return OpenRouterLLM(httpx.Client(transport=httpx.MockTransport(handler)), "key", "test-model")


def _reply(content, **usage):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": usage})


def test_records_tokens_and_cost_for_a_request():
    seen = []
    llm = _llm(lambda request: _reply('{"relevant": []}', prompt_tokens=120, completion_tokens=7, cost=0.002))
    llm.usage_sink = seen.append
    llm.complete_json("system", "x", 100, kind="main")
    assert seen == [
        {"model": "test-model", "kind": "main", "attempts": 1, "prompt_tokens": 120, "completion_tokens": 7,
         "cost": 0.002, "ok": True, "error": None}
    ]


def test_records_a_failed_request(monkeypatch):
    monkeypatch.setattr("app.matching.time.sleep", lambda _: None)
    seen = []
    llm = _llm(lambda request: httpx.Response(500))
    llm.usage_sink = seen.append
    try:
        llm.complete_json("system", "x", 100, kind="ngo-un")
    except RuntimeError:
        pass
    assert len(seen) == 1 and seen[0]["kind"] == "ngo-un" and seen[0]["ok"] is False and seen[0]["attempts"] == 3


def test_a_broken_sink_does_not_break_matching():
    llm = _llm(lambda request: _reply('{"relevant": [1]}'))
    llm.usage_sink = lambda fields: 1 / 0
    assert llm.complete_json("system", "x", 100) == {"relevant": [1]}


def test_an_empty_reply_is_retried_and_logged(monkeypatch):
    monkeypatch.setattr("app.matching.time.sleep", lambda _: None)
    replies = iter([
        httpx.Response(200, json={"choices": [{"message": {"content": None}, "finish_reason": "length"}],
                                  "usage": {"prompt_tokens": 10, "completion_tokens": 600}}),
        _reply('{"relevant": [4]}', prompt_tokens=10, completion_tokens=20),
    ])
    seen = []
    llm = _llm(lambda request: next(replies))
    llm.usage_sink = seen.append
    assert llm.complete_json("system", "x", 100) == {"relevant": [4]}
    assert seen[0]["ok"] is True and seen[0]["attempts"] == 2
    assert (seen[0]["prompt_tokens"], seen[0]["completion_tokens"]) == (20, 620)  # both attempts counted
