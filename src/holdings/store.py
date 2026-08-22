from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Holding:
    kind: str
    code: str
    name: str
    quantity: float
    cost: float
    id: str = ""
    updated_at: str = ""
    quote: dict | None = None
    place: str = ""


@dataclass
class CashBook:
    yongjinbao: float = 0.0
    alipay: float = 0.0
    updated_at: str = ""

    @property
    def known(self) -> bool:
        return bool(self.updated_at)

    @property
    def total(self) -> float:
        return float(self.yongjinbao) + float(self.alipay)


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def cash_file(self) -> Path:
        return self.path.parent / "cash.json"

    def load_cash(self) -> CashBook:
        path = self.cash_file()
        if not path.exists():
            return CashBook()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return CashBook(
            yongjinbao=float(raw.get("yongjinbao") or 0),
            alipay=float(raw.get("alipay") or 0),
            updated_at=str(raw.get("updated_at") or ""),
        )

    def save_cash(self, cash: CashBook) -> CashBook:
        cash.updated_at = cash.updated_at or datetime.now(timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cash_file().write_text(
            json.dumps(asdict(cash), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return cash

    def _load(self) -> list[Holding]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [Holding(**row) for row in raw]

    def _save(self, items: list[Holding]) -> None:
        self.path.write_text(
            json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list(self) -> list[Holding]:
        return self._load()

    def get(self, item_id: str) -> Holding | None:
        for item in self._load():
            if item.id == item_id:
                return item
        return None

    def update_position(self, item_id: str, *, quantity: float, cost: float) -> Holding | None:
        items = self._load()
        found = None
        for item in items:
            if item.id == item_id:
                item.quantity = float(quantity)
                item.cost = round(float(cost), 6)
                item.updated_at = datetime.now(timezone.utc).isoformat()
                found = item
                break
        if found is None:
            return None
        self._save(items)
        return found

    def add(self, item: Holding) -> Holding:
        items = self._load()
        item.id = item.id or uuid.uuid4().hex[:8]
        item.updated_at = datetime.now(timezone.utc).isoformat()
        item.code = item.code.strip()
        items.append(item)
        self._save(items)
        return item

    def delete(self, item_id: str) -> None:
        items = [i for i in self._load() if i.id != item_id]
        self._save(items)

    def save_quotes(self, quotes: dict[str, dict]) -> None:
        items = self._load()
        now = datetime.now(timezone.utc).isoformat()
        for item in items:
            q = quotes.get(item.code)
            if q is not None:
                item.quote = q
                item.updated_at = now
        self._save(items)

    def market_file(self) -> Path:
        return self.path.parent / "market.json"

    def load_market(self) -> dict | None:
        path = self.market_file()
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_market(self, quote: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.market_file().write_text(
            json.dumps(quote, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
