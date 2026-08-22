"""资金流向本地库：data/fflow/{code}.json。通达信当日快照按交易日覆盖写入。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fflow"
START_DATE = "2026-08-10"


def _path(code: str) -> Path:
    return DATA_DIR / f"{code.strip()}.json"


def _norm_date(raw) -> str:
    text = "" if raw is None else str(raw).strip()[:10]
    if not text or text.lower() in ("nan", "nat", "none"):
        return ""
    return text


def session_asof(today: str | date | None = None) -> str:
    """当前（或指定）日历日对应的最近交易日：周末回退到周五。"""
    if today is None:
        d = date.today()
    elif isinstance(today, date):
        d = today
    else:
        d = datetime.strptime(str(today)[:10], "%Y-%m-%d").date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def load(code: str) -> list[dict]:
    path = _path(code)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        day = _norm_date(item.get("date"))
        if not day:
            continue
        try:
            main = float(item.get("main_net"))
        except (TypeError, ValueError):
            continue
        try:
            small = float(item.get("small_net") or 0)
        except (TypeError, ValueError):
            small = 0.0
        out.append({"date": day, "main_net": main, "small_net": small})
    out.sort(key=lambda r: r["date"])
    return out


def save(code: str, rows: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in sorted(rows, key=lambda r: _norm_date(r.get("date"))):
        day = _norm_date(item.get("date"))
        if not day or day in seen:
            continue
        try:
            main = float(item.get("main_net"))
        except (TypeError, ValueError):
            continue
        try:
            small = float(item.get("small_net") or 0)
        except (TypeError, ValueError):
            small = 0.0
        seen.add(day)
        cleaned.append({"date": day, "main_net": main, "small_net": small})
    path = _path(code)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def max_date(code: str) -> str:
    rows = load(code)
    return rows[-1]["date"] if rows else ""


def from_frame(df) -> list[dict]:
    if df is None or getattr(df, "empty", True):
        return []
    if "main_net" not in getattr(df, "columns", []):
        return []
    ordered = df.sort_values("date") if "date" in df.columns else df
    out: list[dict] = []
    for _, item in ordered.iterrows():
        day = _norm_date(item["date"] if "date" in ordered.columns else "")
        if not day:
            continue
        try:
            main = float(item["main_net"])
        except (TypeError, ValueError):
            continue
        try:
            small = float(item["small_net"]) if "small_net" in ordered.columns else 0.0
        except (TypeError, ValueError):
            small = 0.0
        out.append({"date": day, "main_net": main, "small_net": small})
    return out


def to_frame(rows: list[dict]):
    import pandas as pd

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def upsert_snapshot(code: str, df, *, today: str | date | None = None) -> list[dict]:
    """把通达信当日快照按交易日写入本地。日期空则记最近交易日；同日覆盖。失败则原样返回已有历史。"""
    stored = load(code)
    asof = session_asof(today)
    if df is None or getattr(df, "empty", True) or "main_net" not in getattr(df, "columns", []):
        return stored
    work = df.copy()
    if "date" not in work.columns:
        work["date"] = asof
    else:
        work["date"] = [_norm_date(x) or asof for x in work["date"].tolist()]
    incoming = [r for r in from_frame(work) if r["date"] >= START_DATE]
    if not incoming:
        return stored
    by_date = {r["date"]: r for r in stored}
    for row in incoming:
        by_date[row["date"]] = row
    merged = [by_date[k] for k in sorted(by_date)]
    save(code, merged)
    return merged
