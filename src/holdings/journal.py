"""分析快照：每次打开技术页，把当时看到的数据和结论追加到 data/journal/{code}.jsonl。

用途是复盘：过段时间回头看"当时系统看到了什么、预案点位是什么、说明怎么写"。
纯追加、不改历史；记录失败绝不打断页面（调用方负责兜异常）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "journal"


def _path(code: str) -> Path:
    return DATA_DIR / f"{code.strip()}.jsonl"


def record_snapshot(
    code: str,
    *,
    name: str = "",
    price: float | None = None,
    cost: float | None = None,
    stance: str = "",
    trend: str = "",
    note: str = "",
    note_status: str = "",
    overseas_title: str = "",
    defenses: list[dict] | None = None,
    confirm: str = "",
    payload: dict | None = None,
    source: str = "page",
) -> bool:
    """追加一条快照；和上一条的 日期+现价+倾向 完全一样就跳过（防连续刷新刷屏）。

    返回是否真正写入。payload 里可能有 numpy 标量，default=str 兜底。
    """
    code = code.strip()
    if not code:
        return False
    now = datetime.now()
    rec = {
        "ts": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "code": code,
        "name": name,
        "price": price,
        "cost": cost,
        "stance": stance,
        "trend": trend,
        "note": note,
        "note_status": note_status,
        "overseas": overseas_title,
        "defenses": defenses or [],
        "confirm": confirm,
        "payload": payload or {},
        "source": source,
    }
    prev = load_journal(code, limit=1)
    if prev:
        last = prev[0]
        if (
            last.get("date") == rec["date"]
            and last.get("price") == rec["price"]
            and last.get("stance") == rec["stance"]
        ):
            return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _path(code).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    return True


def _load_all(code: str) -> list[dict]:
    """按文件顺序读（最旧在前），供回填重写用。"""
    path = _path(code)
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def load_journal(code: str, limit: int = 200) -> list[dict]:
    """读快照，最新在前；坏行跳过。"""
    out = _load_all(code)
    out.reverse()
    return out[:limit]


def _kline_table(kdf) -> tuple[list[str], list[float]]:
    """日 K → (日期串列表, 收盘列表)，按日期升序。"""
    if kdf is None or getattr(kdf, "empty", True):
        return [], []
    if "date" not in kdf.columns or "close" not in kdf.columns:
        return [], []
    df = kdf.sort_values("date")
    dates = [str(d)[:10] for d in df["date"]]
    closes: list[float] = []
    for c in df["close"]:
        try:
            closes.append(float(c))
        except (TypeError, ValueError):
            closes.append(float("nan"))
    return dates, closes


def backfill_outcomes(code: str, kdf, horizons: tuple[int, ...] = (5, 10)) -> int:
    """用日 K 给老快照补"事后"：N 个交易日后的收盘和相对快照价的涨跌。

    快照日不是交易日时锚到其后第一个交易日。已填的不重算；数据还没走到的留空，
    下次打开技术页接着补。返回本次更新的条数。
    """
    dates, closes = _kline_table(kdf)
    if not dates:
        return 0
    records = _load_all(code)
    changed = 0
    for rec in records:
        later = rec.setdefault("later", {})
        if all(f"{h}d" in later for h in horizons):
            continue
        date_s = str(rec.get("date") or "")[:10]
        if not date_s:
            continue
        anchor = next((i for i, d in enumerate(dates) if d >= date_s), None)
        if anchor is None:
            continue
        base = rec.get("price")
        if not isinstance(base, (int, float)) or base <= 0:
            base = closes[anchor]  # 快照没留价就用锚定日收盘当基准
        if base != base or base <= 0:
            continue
        touched = False
        for h in horizons:
            key = f"{h}d"
            if key in later:
                continue
            j = anchor + h
            if j >= len(dates):
                continue  # 还没走到，留给以后
            close_j = closes[j]
            if close_j != close_j:
                continue
            later[key] = {
                "date": dates[j],
                "close": round(close_j, 4),
                "chg_pct": round((close_j - base) / base * 100, 2),
            }
            touched = True
        if touched:
            changed += 1
    if changed:
        tmp = _path(code).with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        tmp.replace(_path(code))
    return changed


def stance_bucket(stance: str) -> str:
    """倾向文本 → 桶。先看方向词再看观望，避免「偏多但谨慎加仓」被归错。"""
    s = stance or ""
    if "偏多" in s or "偏买" in s:
        return "偏多"
    if "偏空" in s or "偏卖" in s:
        return "偏空"
    if "观望" in s or "不一致" in s:
        return "观望"
    return "其他"


def note_bucket(note: str) -> str:
    """LLM 说明 → 桶。有「判断」段落就只看那一段，避免论证里的词带偏。"""
    s = note or ""
    if "判断" in s:
        s = s[s.rfind("判断") :]
    return stance_bucket(s)


def _hit(bucket: str, chg: float) -> bool | None:
    if bucket == "偏多":
        return chg > 1
    if bucket == "偏空":
        return chg < -1
    if bucket == "观望":
        return abs(chg) <= 2
    return None


def summarize_outcomes(
    records: list[dict],
    horizons: tuple[int, ...] = (5, 10),
    *,
    field: str = "stance",
) -> list[dict]:
    """按倾向桶聚合事后表现。field=stance 用规则，field=note 用说明。"""
    buckets: dict[str, dict[int, list[float]]] = {}
    for r in records:
        later = r.get("later") or {}
        if not later:
            continue
        if field == "note":
            if (r.get("note_status") or "") != "ok":
                continue
            b = note_bucket(r.get("note") or "")
        else:
            b = stance_bucket(r.get("stance") or "")
        for h in horizons:
            o = later.get(f"{h}d")
            if isinstance(o, dict) and isinstance(o.get("chg_pct"), (int, float)):
                buckets.setdefault(b, {}).setdefault(h, []).append(o["chg_pct"])
    rows: list[dict] = []
    for b in ("偏多", "观望", "偏空", "其他"):
        by_h = buckets.get(b)
        if not by_h:
            continue
        row: dict = {"bucket": b}
        for h in horizons:
            vals = by_h.get(h, [])
            if not vals:
                row[f"n{h}"] = 0
                continue
            hits = [x for x in (_hit(b, v) for v in vals) if x is not None]
            row[f"n{h}"] = len(vals)
            row[f"avg{h}"] = round(sum(vals) / len(vals), 2)
            if hits:
                row[f"hit{h}"] = f"{sum(hits)}/{len(vals)}"
        rows.append(row)
    return rows


def summarize_split(records: list[dict]) -> dict[str, list[dict]]:
    """规则 vs 说明两套计分，复盘页并排看谁更准。"""
    return {
        "规则": summarize_outcomes(records, field="stance"),
        "说明": summarize_outcomes(records, field="note"),
    }


def _checks_path(code: str) -> Path:
    return DATA_DIR / f"{code.strip()}.checks.jsonl"


def record_check(
    code: str,
    *,
    side: str,
    price: float,
    qty: float,
    verdict: str,
    title: str,
    reasons: list[str] | None = None,
    past: str = "",
) -> str:
    """记一笔纪律对照，返回 check_id。"""
    from uuid import uuid4

    code = code.strip()
    now = datetime.now()
    cid = now.strftime("%Y%m%d%H%M%S") + "-" + uuid4().hex[:6]
    rec = {
        "id": cid,
        "ts": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "code": code,
        "side": side,
        "price": price,
        "qty": qty,
        "verdict": verdict,
        "title": title,
        "reasons": reasons or [],
        "past": past,
        "followed": None,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _checks_path(code).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    return cid


def load_checks(code: str, limit: int = 100) -> list[dict]:
    path = _checks_path(code)
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    out.reverse()
    return out[:limit]


def mark_followed(code: str, check_id: str, followed: bool) -> bool:
    """给某条对照打「听了/没听」。找到并改了返回 True。"""
    path = _checks_path(code)
    if not path.exists():
        return False
    recs = load_checks(code, limit=10_000)
    recs.reverse()  # 写回要按文件原顺序（旧→新）
    found = False
    for rec in recs:
        if rec.get("id") == check_id:
            rec["followed"] = followed
            found = True
            break
    if not found:
        return False
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for rec in recs:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    tmp.replace(path)
    return True
