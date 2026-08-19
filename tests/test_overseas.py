from holdings.overseas import (
    attach_overseas,
    parse_overseas_payload,
    summarize_overseas,
)
from holdings.tech import TechReport


def _payload():
    return {
        "data": {
            "diff": [
                {"f12": "SOX", "f13": 251, "f14": "费城半导体指数", "f2": 11831.1, "f3": -1.35, "f124": 1787152800},
                {"f12": "AMAT", "f13": 105, "f14": "应用材料", "f2": 495.675, "f3": -3.63, "f124": 1787152800},
                {"f12": "MU", "f13": 105, "f14": "美光科技", "f2": 939.35, "f3": -0.15, "f124": 1787152800},
                {"f12": "US30Y", "f13": 171, "f14": "美国30年期国债收益率", "f2": 5.2088, "f3": -1.48, "f124": 1787152800},
                {"f12": "BROKEN", "f13": 105, "f14": "无价", "f2": "-", "f3": "-"},
            ]
        }
    }


def test_parse_overseas_payload_extracts_and_skips_bad_rows():
    quotes = parse_overseas_payload(_payload())
    assert set(quotes) == {"251.SOX", "105.AMAT", "105.MU", "171.US30Y"}
    sox = quotes["251.SOX"]
    assert sox["name"] == "费城半导体指数"
    assert sox["price"] == 11831.1
    assert sox["change_pct"] == -1.35
    assert sox["ts"] == 1787152800


def test_parse_overseas_payload_empty():
    assert parse_overseas_payload(None) == {}
    assert parse_overseas_payload({}) == {}


def test_summarize_overseas_groups_and_hint():
    block = summarize_overseas(parse_overseas_payload(_payload()))
    assert block.ok
    assert "费半" in block.title
    blob = "".join(block.evidence)
    assert "应用材料" in blob and "美光" in blob
    assert "美国30年期国债收益率" in blob and "回落" in blob
    assert "幅度一般" in blob  # -1.35% 落在 1~3 之间


def test_summarize_overseas_big_drop_warns():
    quotes = parse_overseas_payload(_payload())
    quotes["251.SOX"]["change_pct"] = -4.98
    block = summarize_overseas(quotes)
    assert "承压" in "".join(block.evidence)


def test_summarize_overseas_empty():
    block = summarize_overseas({})
    assert not block.ok
    assert "暂时没有" in block.title


def test_attach_overseas_never_breaks(monkeypatch):
    def boom(timeout=8.0):
        raise RuntimeError("network down")

    monkeypatch.setattr("holdings.overseas.fetch_overseas", boom)
    report = TechReport(stance="x", stance_evidence=[], signals=[], quiet=[])
    out = attach_overseas(report)
    assert out.overseas is not None
    assert not out.overseas.ok
