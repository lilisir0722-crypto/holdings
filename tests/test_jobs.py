from holdings.jobs import push_wechat
from holdings.pipeline import TechRun, persist_run
from holdings.plan import PlanView
from holdings.store import Holding
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
