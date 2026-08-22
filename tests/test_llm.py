import json

from holdings import llm


class _Resp:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def decode(self, _enc="utf-8"):
        return self.read().decode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_explain_tech_skipped_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    text, status = llm.explain_tech({"代码": "562590", "现价": 1.05})
    assert status == "skipped"
    assert text is None


def test_explain_tech_incomplete_read_is_error(monkeypatch):
    import http.client

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    llm.clear_explain_cache()

    def boom(req, timeout=20):
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    text, status = llm.explain_tech({"代码": "562590", "现价": 1.05})
    assert status == "error"
    assert "IncompleteRead" in (text or "")


def test_explain_tech_reuses_cache_for_same_code_and_price(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    llm.clear_explain_cache()
    calls = {"n": 0}

    def fake_urlopen(req, timeout=20):
        calls["n"] += 1
        return _Resp(
            {
                "choices": [
                    {"message": {"content": "先看日线偏弱，成本还在亏，更宜观望。"}}
                ]
            }
        )

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    payload = {"代码": "562590", "现价": 1.05, "总倾向": "更宜观望。"}
    t1, s1 = llm.explain_tech(payload)
    t2, s2 = llm.explain_tech(payload)
    assert s1 == "ok" and s2 == "ok"
    assert t1 == t2
    assert calls["n"] == 1


def test_explain_tech_misses_cache_when_price_changes(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    llm.clear_explain_cache()
    calls = {"n": 0}

    def fake_urlopen(req, timeout=20):
        calls["n"] += 1
        return _Resp({"choices": [{"message": {"content": f"第{calls['n']}次"}}]})

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    llm.explain_tech({"代码": "562590", "现价": 1.05})
    llm.explain_tech({"代码": "562590", "现价": 1.06})
    assert calls["n"] == 2


def test_chat_with_page_puts_payload_in_system_every_turn(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    captured = []

    def fake_urlopen(req, timeout=20):
        captured.append(json.loads(req.data.decode("utf-8")))
        return _Resp({"choices": [{"message": {"content": "按这页数据看，先观望。"}}]})

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    payload = {"代码": "562590", "现价": 1.05, "成本": 1.14}
    text, status, *_rest = llm.chat_with_page(payload, history=[], message="现在能加吗")
    assert status == "ok"
    assert "观望" in text
    sys0 = captured[0]["messages"][0]["content"]
    assert "562590" in sys0
    assert "1.05" in sys0
    assert captured[0]["messages"][-1]["content"] == "现在能加吗"

    payload2 = {"代码": "562590", "现价": 1.08, "成本": 1.14}
    history = [
        {"role": "user", "content": "现在能加吗"},
        {"role": "assistant", "content": "按这页数据看，先观望。"},
    ]
    llm.chat_with_page(payload2, history=history, message="那防线呢")
    sys1 = captured[1]["messages"][0]["content"]
    assert "1.08" in sys1
    assert captured[1]["messages"][-1]["content"] == "那防线呢"
    roles = [m["role"] for m in captured[1]["messages"]]
    assert roles[0] == "system"
    assert "user" in roles and "assistant" in roles


def test_chat_with_page_uses_selected_model(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    captured = []

    def fake_urlopen(req, timeout=20):
        captured.append(json.loads(req.data.decode("utf-8")))
        return _Resp({"choices": [{"message": {"content": "答"}}]})

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    llm.chat_with_page(
        {"代码": "562590"},
        history=[],
        message="问",
        model="deepseek-v4-pro",
    )
    assert captured[0]["model"] == "deepseek-v4-pro"


def test_chat_with_page_ignores_unknown_model(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    captured = []

    def fake_urlopen(req, timeout=20):
        captured.append(json.loads(req.data.decode("utf-8")))
        return _Resp({"choices": [{"message": {"content": "答"}}]})

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    llm.chat_with_page({"代码": "562590"}, history=[], message="问", model="gpt-whatever")
    assert captured[0]["model"] == "deepseek-v4-flash"
