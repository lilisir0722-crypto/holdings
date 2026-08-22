from holdings.store import Holding, Store
from holdings.web import format_beijing


def test_format_beijing_from_utc_iso():
    assert format_beijing("2026-08-19T23:20:43.478909+00:00") == "2026-08-20 07:20:43"


def test_format_beijing_zulu_and_naive():
    assert format_beijing("2026-08-19T23:20:43Z") == "2026-08-20 07:20:43"
    assert format_beijing("2026-08-19T23:20:43") == "2026-08-20 07:20:43"


def test_format_beijing_empty_and_junk():
    assert format_beijing(None) == ""
    assert format_beijing("") == ""
    assert format_beijing("not-a-time") == "not-a-time"


def test_add_lot_endpoint_updates_cost(tmp_path, monkeypatch):
    import holdings.lots as lots
    import holdings.web as web
    from fastapi.testclient import TestClient

    monkeypatch.setattr(lots, "DATA_DIR", tmp_path / "lots")
    store = Store(tmp_path / "holdings.json")
    hit = store.add(Holding(kind="基金", code="562590", name="半导", quantity=1000, cost=1.0))
    monkeypatch.setattr(web, "store", store)
    client = TestClient(web.app)
    r = client.post(
        f"/add-lot/{hit.id}",
        data={"quantity": "1000", "price": "1.2"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    updated = store.get(hit.id)
    assert updated is not None
    assert updated.quantity == 2000
    assert round(updated.cost, 4) == 1.1


def test_lots_page_seeds_opening(tmp_path, monkeypatch):
    import holdings.lots as lots
    import holdings.web as web
    from fastapi.testclient import TestClient

    monkeypatch.setattr(lots, "DATA_DIR", tmp_path / "lots")
    store = Store(tmp_path / "holdings.json")
    hit = store.add(Holding(kind="基金", code="562590", name="半导", quantity=1000, cost=1.0))
    monkeypatch.setattr(web, "store", store)
    client = TestClient(web.app)
    r = client.get(f"/lots/{hit.id}")
    assert r.status_code == 200
    assert "开仓" in r.text
    assert "1.0000" in r.text


def test_delete_lot_endpoint_recalculates(tmp_path, monkeypatch):
    import holdings.lots as lots
    import holdings.web as web
    from fastapi.testclient import TestClient

    monkeypatch.setattr(lots, "DATA_DIR", tmp_path / "lots")
    store = Store(tmp_path / "holdings.json")
    hit = store.add(Holding(kind="基金", code="562590", name="半导", quantity=1000, cost=1.0))
    monkeypatch.setattr(web, "store", store)
    lots.apply_buy(store, hit, quantity=1000, price=1.2)
    extra = lots.load_lots(hit.id)[-1]
    client = TestClient(web.app)
    r = client.post(f"/delete-lot/{hit.id}/{extra['id']}", follow_redirects=False)
    assert r.status_code == 303
    updated = store.get(hit.id)
    assert updated is not None
    assert updated.quantity == 1000
    assert round(updated.cost, 4) == 1.0


def test_tech_shell_does_not_run_analysis(tmp_path, monkeypatch):
    import holdings.web as web
    from fastapi.testclient import TestClient

    store = Store(tmp_path / "holdings.json")
    store.add(Holding(kind="基金", code="562590", name="半导", quantity=1000, cost=1.14))
    monkeypatch.setattr(web, "store", store)

    def boom(*args, **kwargs):
        raise AssertionError("打开详情页不该立刻跑完整分析")

    monkeypatch.setattr(web, "run_tech", boom)
    client = TestClient(web.app)
    r = client.get("/tech/562590")
    assert r.status_code == 200
    assert 'id="tech-core"' in r.text
    assert 'id="tech-rest"' in r.text
    assert 'id="tech-chat"' in r.text
    assert 'data-tab="plan"' in r.text
    assert 'data-tab="intent"' in r.text
    assert "主力意图" in r.text
    assert "问这页" in r.text
    assert 'data-tab="chat"' not in r.text


def test_tech_core_fragment_and_chat(tmp_path, monkeypatch):
    import holdings.llm as llm
    import holdings.pipeline as pipeline
    import holdings.web as web
    from fastapi.testclient import TestClient

    pipeline.clear_page_runs()
    monkeypatch.setattr(
        pipeline, "_fetch_ctx", lambda *a, **k: (None, pipeline._empty_ctx())
    )
    monkeypatch.setattr(pipeline, "attach_overseas", lambda report, **kw: report)
    monkeypatch.setattr(
        llm,
        "chat_with_page",
        lambda payload, history, message, model=None: (f"回：{message}", "ok", ""),
    )
    store = Store(tmp_path / "holdings.json")
    store.add(Holding(kind="基金", code="562590", name="半导", quantity=1000, cost=1.14))
    monkeypatch.setattr(web, "store", store)
    client = TestClient(web.app)
    blocked = client.post("/tech/562590/chat", json={"message": "能加吗", "history": []})
    assert blocked.status_code == 409
    core = client.get("/tech/562590/core")
    assert core.status_code == 200
    assert "没有够用的日 K" in core.text
    chat = client.post(
        "/tech/562590/chat",
        json={"message": "能加吗", "history": [], "model": "deepseek-v4-pro"},
    )
    assert chat.status_code == 200
    assert chat.json()["text"] == "回：能加吗"
