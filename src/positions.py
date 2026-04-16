"""포지션 로더 + 손익 계산 + 목표가/손절가 감지.

저장은 src/storage/positions_store.py가 담당 (로컬 YAML 또는 Upstash Redis).
"""
from dataclasses import dataclass

from src.storage import positions_store


@dataclass
class Position:
    code: str
    name: str
    buy_price: float
    quantity: int
    buy_date: str = ""
    note: str = ""
    target_price: float | None = None
    stop_loss: float | None = None
    market: str = "KS"        # watchlist와 매칭 시 채워짐

    @property
    def cost(self) -> float:
        return self.buy_price * self.quantity

    def pnl(self, current_price: float) -> dict:
        """현재가 입력 시 손익 정보 반환"""
        current_value = current_price * self.quantity
        unrealized = current_value - self.cost
        pct = (current_price - self.buy_price) / self.buy_price * 100 if self.buy_price else 0
        return {
            "current_price": current_price,
            "current_value": current_value,
            "unrealized": unrealized,
            "pct": pct,
            "target_hit": (self.target_price is not None and current_price >= self.target_price),
            "stop_hit": (self.stop_loss is not None and current_price <= self.stop_loss),
        }

    def to_dict(self) -> dict:
        d = {
            "code": self.code,
            "name": self.name,
            "buy_price": self.buy_price,
            "quantity": self.quantity,
            "buy_date": self.buy_date,
            "note": self.note,
        }
        if self.target_price is not None:
            d["target_price"] = self.target_price
        if self.stop_loss is not None:
            d["stop_loss"] = self.stop_loss
        return d


def _from_raw(p: dict) -> Position:
    return Position(
        code=str(p["code"]),
        name=p.get("name", str(p["code"])),
        buy_price=float(p["buy_price"]),
        quantity=int(p["quantity"]),
        buy_date=str(p.get("buy_date", "")),
        note=str(p.get("note", "")),
        target_price=float(p["target_price"]) if p.get("target_price") else None,
        stop_loss=float(p["stop_loss"]) if p.get("stop_loss") else None,
    )


def load() -> list[Position]:
    try:
        raw_list = positions_store.list_positions()
        return [_from_raw(p) for p in raw_list]
    except Exception as e:
        print(f"[positions] 로드 실패: {e}")
        return []


def enrich_with_market(positions: list[Position], watchlist: list[dict]) -> None:
    """watchlist에 있는 종목은 market 정보 채워넣음"""
    market_map = {s["code"]: s.get("market", "KS") for s in watchlist}
    for p in positions:
        p.market = market_map.get(p.code, "KS")


if __name__ == "__main__":
    ps = load()
    print(f"포지션 {len(ps)}개:")
    for p in ps:
        print(f"  - {p.name} {p.quantity}주 @₩{p.buy_price:,.0f} (cost ₩{p.cost:,.0f})")
        if p.target_price:
            print(f"      목표가 ₩{p.target_price:,.0f}")
        if p.stop_loss:
            print(f"      손절가 ₩{p.stop_loss:,.0f}")
