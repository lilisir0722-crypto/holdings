from holdings.jobs import job_close, push_wechat
from holdings.pipeline import TechRun, persist_run
from holdings.plan import PlanView
from holdings.store import Holding, Store
from holdings.tech import TechReport


def test_push_wechat_without_key_returns_false(monkeypatch):
    monkeypatch.delenv("SERVERCHAN_SENDKEY", raising=False)
    monkeypatch.delenv("SCKEY", raising=False)
    assert push_wechat("盘前", "正文") is False


def test_persist_run_skips_on_error(tmp_path, monkeypatch):
    import holdings.journal as journal

    monkeypatch.setattr(journal, "DATA_DIR", tmp_path)
    run = TechRun(code="562590", name="x", kind="基金", price=1.0, error="行情连不上")
    assert persist_run(run, Holding(kind="基金", code="562590", name="x", quantity=1, cost=1)) is False


def test_persist_run_writes(tmp_path, monkeypatch):
    import holdings.journal as journal

    monkeypatch.setattr(journal, "DATA_DIR", tmp_path)
    report = TechReport(stance="观望", stance_evidence=[], signals=[], quiet=[], trend_title="震荡")
    run = TechRun(
        code="562590",
        name="半导",
        kind="基金",
        price=1.04,
        report=report,
        plan=PlanView(has=False),
        payload={"现价": 1.04},
    )
    hit = Holding(kind="基金", code="562590", name="半导", quantity=1, cost=1.14)
    assert persist_run(run, hit, source="close") is True
    recs = journal.load_journal("562590")
    assert recs[0]["source"] == "close"
    assert recs[0]["stance"] == "观望"


def test_job_close_keeps_going_when_one_stock_fails(tmp_path, monkeypatch):
    import json

    import holdings.jobs as jobs

    store = Store(tmp_path / "holdings.json")
    store.path.write_text(
        json.dumps(
            [
                {
                    "kind": "基金",
                    "code": "562590",
                    "name": "半导",
                    "quantity": 1,
                    "cost": 1,
                    "id": "a",
                    "updated_at": "",
                    "quote": None,
                    "place": "",
                },
                {
                    "kind": "基金",
                    "code": "159530",
                    "name": "机器人",
                    "quantity": 1,
                    "cost": 1,
                    "id": "b",
                    "updated_at": "",
                    "quote": None,
                    "place": "",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_run(store, hit, holdings, mode="full"):
        if hit.code == "562590":
            raise RuntimeError("模型断了")
        report = TechReport(stance="观望", stance_evidence=[], signals=[], quiet=[], trend_title="震荡")
        return TechRun(code=hit.code, name=hit.name, kind=hit.kind, price=1.0, report=report, payload={})

    monkeypatch.setattr(jobs, "fetch_all", lambda holdings: ({}, {}))
    monkeypatch.setattr(jobs, "run_tech", fake_run)
    monkeypatch.setattr(jobs, "persist_run", lambda *args, **kwargs: True)
    out = job_close(store)
    assert out["ok"] is True
    assert out["items"][0]["error"] == "模型断了"
    assert out["items"][1]["wrote"] is True
    assert out["items"][1]["error"] is None
