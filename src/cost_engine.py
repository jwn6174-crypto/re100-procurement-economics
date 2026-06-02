"""
RE100 이행수단 비용엔진 (라이브러리 · v3)
==========================================
v3 변경점: 기업 특성이 엔진에 실제로 반영되도록 연결
  - 규모 → PPA 협상력(ppa_position 자동 도출): 클수록 바닥에 가깝게(저렴)
  - 규모 → 직접 PPA 적격성: ppa_min_gwh 미만이면 직접 PPA 불가
  - 부지 → 자가발전 게이팅(has_land)
  - ETS 편입(ets_covered): Phase 1 단가엔 무영향, Phase 3 적격성 보정에서 사용
주의: 현재 고REC 국면(SMP+REC>천장)에서는 PPA가 바닥에 고정되어
      '규모→협상력' 채널이 잠복함. REC 하락 시나리오(Phase 4)에서 활성화됨.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class MarketData:
    smp: float = 115.0
    rec_per_kwh: float = 70.0
    green_premium_adder: float = 11.0
    industrial_tariff: float = 179.0
    industrial_energy_charge: float = 120.0
    network_charge_3rd: float = 25.0
    network_charge_direct: float = 8.0
    transaction_fee_direct: float = 0.0

    @property
    def non_energy_charge(self) -> float:
        return self.industrial_tariff - self.industrial_energy_charge


@dataclass
class PVParams:
    capex_per_kw: float = 1_300_000.0
    om_per_kw_yr: float = 35_000.0
    capacity_factor: float = 0.15
    lifetime_yr: int = 20
    discount_rate: float = 0.045


def derive_ppa_position(consumption_gwh: float) -> float:
    """규모가 클수록 협상력↑ → 바닥(0)에 가깝게."""
    if consumption_gwh >= 100:
        return 0.30
    if consumption_gwh >= 20:
        return 0.50
    return 0.70


@dataclass
class FirmProfile:
    name: str
    annual_consumption_gwh: float
    sector: str = ""
    re_target_share: float = 1.0
    has_land: bool = True
    ets_covered: bool = False
    ppa_ceiling_ratio: float = 0.95
    ppa_position: Optional[float] = None   # None이면 규모에서 자동 도출
    ppa_min_gwh: float = 10.0              # 직접 PPA 최소 규모

    def __post_init__(self):
        if self.ppa_position is None:
            self.ppa_position = derive_ppa_position(self.annual_consumption_gwh)

    @property
    def direct_ppa_available(self) -> bool:
        return self.annual_consumption_gwh * self.re_target_share >= self.ppa_min_gwh


def crf(rate: float, n: int) -> float:
    return rate * (1 + rate) ** n / ((1 + rate) ** n - 1)


def pv_lcoe(pv: PVParams) -> float:
    annualized_capex = pv.capex_per_kw * crf(pv.discount_rate, pv.lifetime_yr)
    return (annualized_capex + pv.om_per_kw_yr) / (8760 * pv.capacity_factor)


def ppa_bounds(m: MarketData, firm: FirmProfile):
    floor = m.smp + m.rec_per_kwh
    ceiling = m.industrial_energy_charge * firm.ppa_ceiling_ratio
    return floor, ceiling


def ppa_energy_price(m: MarketData, firm: FirmProfile):
    floor, ceiling = ppa_bounds(m, firm)
    if floor < ceiling:
        return floor + (ceiling - floor) * firm.ppa_position, False
    return floor, True


def cost_engine(m: MarketData, pv: PVParams, firm: FirmProfile, mode: str = "total") -> dict:
    ppa_e, _ = ppa_energy_price(m, firm)
    direct = (ppa_e + m.non_energy_charge + m.network_charge_direct + m.transaction_fee_direct) \
        if firm.direct_ppa_available else None
    total = {
        "녹색프리미엄": m.industrial_tariff + m.green_premium_adder,
        "REC 구매": m.industrial_tariff + m.rec_per_kwh,
        "제3자 PPA": ppa_e + m.non_energy_charge + m.network_charge_3rd,
        "직접 PPA": direct,
        "자가발전": pv_lcoe(pv) if firm.has_land else None,
    }
    if mode == "total":
        return total
    if mode == "premium":
        return {k: (v - m.industrial_tariff if v is not None else None) for k, v in total.items()}
    raise ValueError("mode must be 'total' or 'premium'")


def rank_costs(costs: dict) -> dict:
    valid = {k: v for k, v in costs.items() if v is not None}
    return {k: i + 1 for i, k in enumerate(sorted(valid, key=valid.get))}