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
