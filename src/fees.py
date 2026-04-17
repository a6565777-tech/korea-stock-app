"""토스증권 수수료·세금 계산 유틸.

기준(2026-04 현재):
- 매수/매도 위탁수수료: 체결금액 × 0.015% (MTS·HTS 공통)
- 유관기관 수수료: 체결금액 × 0.0036396% (거래소·예탁원 등)
- 매도 시 증권거래세·농특세:
    코스피(KS): 거래세 0.03% + 농특세 0.15% = 0.18%
    코스닥(KQ): 거래세 0.18%
  (코넥스·해외는 범위 밖)

사용자가 알고 싶은 것: "목표가 도달 시 실제로 손에 쥐는 돈".
따라서 순수익 계산 시 매수·매도 수수료 + 매도 시 거래세를 전부 반영.
"""
from __future__ import annotations

# 율은 소수 (0.00015 = 0.015%)
BROKERAGE_RATE = 0.00015              # 위탁수수료 (편도)
INFRASTRUCTURE_RATE = 0.0000036396    # 유관기관 (편도)
EXCISE_TAX_KS = 0.0018                # 코스피 거래세+농특세 합 0.18% (매도만)
EXCISE_TAX_KQ = 0.0018                # 코스닥 거래세 0.18% (매도만)


def buy_cost(price: float, quantity: int) -> dict:
    """매수 시 총 지출.

    Returns: {
        principal: 원금 (price * qty),
        brokerage: 위탁수수료,
        infrastructure: 유관기관수수료,
        total_fee: 수수료 합,
        total_cost: 총 지출 (원금 + 수수료)
    }
    """
    principal = price * quantity
    brokerage = principal * BROKERAGE_RATE
    infra = principal * INFRASTRUCTURE_RATE
    total_fee = brokerage + infra
    return {
        "principal": principal,
        "brokerage": brokerage,
        "infrastructure": infra,
        "total_fee": total_fee,
        "total_cost": principal + total_fee,
    }


def sell_proceeds(price: float, quantity: int, market: str = "KS") -> dict:
    """매도 시 실수령액.

    Returns: {
        gross: 총 매도금액 (price * qty),
        brokerage: 위탁수수료,
        infrastructure: 유관기관수수료,
        excise_tax: 거래세+농특세,
        total_deduction: 차감 합,
        net_proceeds: 실수령액 (gross - 차감)
    }
    """
    gross = price * quantity
    brokerage = gross * BROKERAGE_RATE
    infra = gross * INFRASTRUCTURE_RATE
    excise = gross * (EXCISE_TAX_KS if market.upper() != "KQ" else EXCISE_TAX_KQ)
    total_ded = brokerage + infra + excise
    return {
        "gross": gross,
        "brokerage": brokerage,
        "infrastructure": infra,
        "excise_tax": excise,
        "total_deduction": total_ded,
        "net_proceeds": gross - total_ded,
    }


def roundtrip_pnl(buy_price: float, sell_price: float, quantity: int, market: str = "KS") -> dict:
    """매수→매도 왕복 시 실 손익.

    Returns: {
        gross_pnl: 수수료 전 손익 (단순 차액 × 수량),
        gross_pct: 수수료 전 수익률 %,
        total_fees: 매수·매도 수수료·세금 합,
        net_pnl: 실손익 (수수료·세금 반영),
        net_pct: 실수익률 % (투입 원금 대비),
        buy: buy_cost(),
        sell: sell_proceeds(),
    }
    """
    buy = buy_cost(buy_price, quantity)
    sell = sell_proceeds(sell_price, quantity, market)
    gross_pnl = sell["gross"] - buy["principal"]
    gross_pct = (gross_pnl / buy["principal"] * 100) if buy["principal"] else 0.0
    total_fees = buy["total_fee"] + sell["total_deduction"]
    net_pnl = sell["net_proceeds"] - buy["total_cost"]
    net_pct = (net_pnl / buy["total_cost"] * 100) if buy["total_cost"] else 0.0
    return {
        "gross_pnl": gross_pnl,
        "gross_pct": gross_pct,
        "total_fees": total_fees,
        "net_pnl": net_pnl,
        "net_pct": net_pct,
        "buy": buy,
        "sell": sell,
    }


def breakeven_price(buy_price: float, market: str = "KS") -> float:
    """본전 가격 — 이 가격에 팔아야 수수료·세금 감안 순손익 0.

    buy_price × (1 + BROKERAGE + INFRA) = sell_price × (1 - BROKERAGE - INFRA - EXCISE)
    → sell_price = buy_price × (1 + BROKERAGE + INFRA) / (1 - BROKERAGE - INFRA - EXCISE)
    """
    buy_rate = 1 + BROKERAGE_RATE + INFRASTRUCTURE_RATE
    excise = EXCISE_TAX_KQ if market.upper() == "KQ" else EXCISE_TAX_KS
    sell_rate = 1 - BROKERAGE_RATE - INFRASTRUCTURE_RATE - excise
    return buy_price * buy_rate / sell_rate if sell_rate else buy_price


if __name__ == "__main__":
    # 빠른 검산: 10만원 × 10주 기준 1% 수익 시 실손익
    r = roundtrip_pnl(100_000, 101_000, 10, "KS")
    print(f"gross: {r['gross_pnl']:+,.0f}원 ({r['gross_pct']:+.3f}%)")
    print(f"net:   {r['net_pnl']:+,.0f}원 ({r['net_pct']:+.3f}%)")
    print(f"total fees: {r['total_fees']:,.0f}원")
    print(f"breakeven: ₩{breakeven_price(100_000):,.2f}")
