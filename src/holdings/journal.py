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


def load_journal(code: str, limit: int = 200) -> list[dict]:
    """读快照，最新在前；坏行跳过。"""
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
    out.reverse()
    return out[:limit]
