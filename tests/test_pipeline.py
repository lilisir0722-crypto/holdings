from holdings.pipeline import run_tech
from holdings.store import Holding, Store


def _holding(store: Store) -> Holding:
    return store.add(
        Holding(kind="基金", code="562590", name="半导", quantity=1000, cost=1.14)
    )


def test_core_mode_skips_llm_and_overseas(tmp_path, monkeypatch):
    import holdings.pipeline as pipeline

    monkeypatch.setattr(
        pipeline, "_fetch_ctx", lambda *a, **k: (None, pipeline._empty_ctx())
    )

    def no_overseas(report, **kwargs):
        raise AssertionError("core 不该拉外部参照")

    monkeypatch.setattr(pipeline, "attach_overseas", no_overseas)
    store = Store(tmp_path / "holdings.json")
    run = run_tech(store, _holding(store), mode="core")
    assert run.report is not None
    assert run.error is None
    assert not run.report.model_note
    assert run.report.overseas is None


def test_fill_note_uses_current_payload(tmp_path, monkeypatch):
    import holdings.llm as llm
    import holdings.pipeline as pipeline

    monkeypatch.setattr(
        pipeline, "_fetch_ctx", lambda *a, **k: (None, pipeline._empty_ctx())
    )
    monkeypatch.setattr(
        pipeline,
        "attach_overseas",
        lambda report, **kwargs: report,
    )
    monkeypatch.setattr(llm, "explain_tech", lambda payload: ("说明正文", "ok"))
    store = Store(tmp_path / "holdings.json")
    hit = _holding(store)
    run = run_tech(store, hit, mode="core")
    pipeline.fill_note(run, store, hit)
    assert run.report.model_note == "说明正文"
    assert run.report.model_status == "ok"
    assert run.payload.get("代码") == "562590"


def test_fill_extras_sets_intent_payload(tmp_path, monkeypatch):
    import holdings.pipeline as pipeline

    monkeypatch.setattr(
        pipeline, "_fetch_ctx", lambda *a, **k: (None, pipeline._empty_ctx())
    )
    monkeypatch.setattr(
        pipeline, "_fetch_extras_ctx", lambda *a, **k: pipeline._empty_ctx()
    )
    monkeypatch.setattr(pipeline, "attach_overseas", lambda report, **kwargs: report)
    store = Store(tmp_path / "holdings.json")
    hit = _holding(store)
    run = run_tech(store, hit, mode="core")
    pipeline.fill_extras(run, store, hit)
    assert run.report.intent is not None
    assert run.report.intent.title
    assert run.payload.get("主力意图")


def test_fill_capital_history_persists_tdx_snapshot(tmp_path, monkeypatch):
    import pandas as pd
    import holdings.fflow as fflow
    import holdings.pipeline as pipeline

    monkeypatch.setattr(fflow, "DATA_DIR", tmp_path / "fflow")
    monkeypatch.setattr(fflow, "session_asof", lambda today=None: "2026-08-21")
    fflow.save(
        "562590",
        [{"date": "2026-08-20", "main_net": 1.0, "small_net": 0.0}],
    )
    ctx = {
        "capital_df": pd.DataFrame(
            [{"date": "", "main_net": -4.17e7, "small_net": 4.17e7}]
        )
    }
    pipeline._fill_capital_history(ctx, "562590")
    assert len(ctx["capital_df"]) == 2
    assert str(ctx["capital_df"].iloc[-1]["date"])[:10] == "2026-08-21"
    assert abs(float(ctx["capital_df"].iloc[-1]["main_net"]) + 4.17e7) < 1
    stored = fflow.load("562590")
    assert [r["date"] for r in stored] == ["2026-08-20", "2026-08-21"]


def test_fill_capital_history_keeps_store_when_tdx_empty(tmp_path, monkeypatch):
    import pandas as pd
    import holdings.fflow as fflow
    import holdings.pipeline as pipeline

    monkeypatch.setattr(fflow, "DATA_DIR", tmp_path / "fflow")
    fflow.save(
        "562590",
        [{"date": "2026-08-20", "main_net": 1.0, "small_net": 0.0}],
    )
    ctx = {"capital_df": None}
    pipeline._fill_capital_history(ctx, "562590")
    assert len(ctx["capital_df"]) == 1
    assert str(ctx["capital_df"].iloc[0]["date"])[:10] == "2026-08-20"
