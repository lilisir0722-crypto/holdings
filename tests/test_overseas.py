from holdings.overseas import (
    attach_overseas,
    parse_futures_payload,
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
                {"f12": "002371", "f13": 0, "f14": "北方华创", "f2": 712.95, "f3": -8.24, "f124": 1787152800},
                {"f12": "931743", "f13": 2, "f14": "半导体材料设备", "f2": 5123.4, "f3": -7.10, "f124": 1787152800},
                {"f12": "US30Y", "f13": 171, "f14": "美国30年期国债收益率", "f2": 5.2088, "f3": -1.48, "f124": 1787152800},
                {"f12": "US10Y", "f13": 171, "f14": "美国10年期国债收益率", "f2": 4.6506, "f3": 0.04, "f124": 1787152800},
                {"f12": "UDI", "f13": 100, "f14": "美元指数", "f2": 98.83, "f3": 0.03, "f124": 1787152800},
                {"f12": "USDCNH", "f13": 133, "f14": "美元兑离岸人民币", "f2": 6.7321, "f3": 0.01, "f124": 1787152800},
                {"f12": "BROKEN", "f13": 105, "f14": "无价", "f2": "-", "f3": "-"},
            ]
        }
    }


def _futures_payload(price=29653.35, zdf=0.48):
    return {
        "qt": {
            "dm": "NQ00Y",
            "name": "小型纳指当月连续",
            "p": price,
            "zdf": zdf,
            "spsj": 1787259600,
        }
    }


def test_parse_overseas_payload_extracts_and_skips_bad_rows():
    quotes = parse_overseas_payload(_payload())
    assert set(quotes) == {
        "251.SOX", "105.AMAT", "105.MU", "0.002371", "2.931743",
        "171.US30Y", "171.US10Y", "100.UDI", "133.USDCNH",
    }
    sox = quotes["251.SOX"]
    assert sox["name"] == "费城半导体指数"
    assert sox["price"] == 11831.1
    assert sox["change_pct"] == -1.35
    assert sox["ts"] == 1787152800


def test_parse_overseas_payload_empty():
    assert parse_overseas_payload(None) == {}
    assert parse_overseas_payload({}) == {}


def test_parse_futures_payload():
    q = parse_futures_payload(_futures_payload(), "纳指期货")
    assert q["name"] == "小型纳指当月连续"
    assert q["price"] == 29653.35
    assert q["change_pct"] == 0.48
    assert q["ts"] == 1787259600
    assert parse_futures_payload(None, "x") is None
    assert parse_futures_payload({"qt": {"p": "-"}}, "x") is None


def test_summarize_overseas_groups_and_hint():
    block = summarize_overseas(parse_overseas_payload(_payload()))
    assert block.ok
    assert "费半" in block.title
    blob = "".join(block.evidence)
    assert "应用材料" in blob and "美光" in blob
    assert "美国30年期国债收益率" in blob and "回落" in blob
    assert "幅度一般" in blob  # -1.35% 落在 1~3 之间


def test_summarize_overseas_new_groups():
    block = summarize_overseas(parse_overseas_payload(_payload()))
    blob = "".join(block.evidence)
    assert "龙头：北方华创 -8.24%" in blob
    assert "行业：半导体材料设备 -7.10%" in blob
    assert "美国10年期国债收益率 4.6506%，持平" in blob  # 0.04% 小于 0.05 的持平阈值
    assert "美元指数 98.8300" in blob
    assert "USDCNH 上行" in blob  # 汇率注释


def test_summarize_overseas_futures_group_and_hint():
    quotes = parse_overseas_payload(_payload())
    quotes["103.NQ00Y"] = parse_futures_payload(_futures_payload(zdf=1.24), "纳指期货")
    block = summarize_overseas(quotes)
    blob = "".join(block.evidence)
    assert "期货：小型纳指当月连续 +1.24%" in blob
    assert "高开" in blob
    assert "纳指期货 +1.24%" in block.title


def test_summarize_overseas_futures_quiet_no_hint():
    quotes = parse_overseas_payload(_payload())
    quotes["103.NQ00Y"] = parse_futures_payload(_futures_payload(zdf=0.48), "纳指期货")
    block = summarize_overseas(quotes)
    blob = "".join(block.evidence)
    assert "期货：" in blob
    assert "高开" not in blob and "低开" not in blob


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
