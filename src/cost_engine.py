"""
RE100 이행수단 비용엔진 (라이브러리 · v4)
==========================================
v4 변경점: '부지 보유(has_land, 불리언)' 축을 폐지하고,
           자가발전을 '수요 커버리지 비율(0~1)'로 모델링.
  - 가용 부지면적(㎡) → 설치가능 용량 → 연간 발전량 → 수요 대비 커버리지 비율
  - 자가발전 비용 = 커버리지비율 × 자가단가(LCOE) + (1−비율) × 보완수단단가
    (보완수단 = 직접 PPA 가능 시 직접 PPA, 아니면 REC)
  - 이로써 "부지는 있으나 수요가 거대한 반도체(낮은 커버리지)"와
    "부지 대비 수요가 작은 중소 제조(높은 커버리지)"가 자연스럽게 구분됨.

축(3개): 소비규모 / ETS 편입 / 자가발전 커버리지(부지면적+수요로 산출)

근거·출처 메모:
  - 태양광 설치계수(kW/㎡)·이용률: NREL/업계 통용 표준값(임시 기본값, 갱신 가능)
  - LCOE 방식: IRENA·IEA·NREL 표준 / 국내 적용 신경철 외(2024)
  - 부지면적·소비규모: 대표 대기업 스케일의 추정치(임시값, 한전 데이터·기업공시로 갱신)
  - 직접 PPA 접근성: 제도상 소비량 하한은 없음(2025.7 On-Site 1MW 폐지, 제3자 300kW).
    소형기업 'available=False'는 법적 금지가 아니라 협상·계약 부담을 반영한 가정.
"""
from dataclasses import dataclass
from typing import Optional
import unicodedata


# ── 표 정렬 헬퍼: 한글(전각)을 폭 2로 계산해 칸을 맞춘다 ──────────────
def _w(s: str) -> int:
    """문자열의 표시 폭(전각=2, 반각=1)."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in str(s))


def pad(s: str, width: int, align: str = "left") -> str:
    """표시 폭 기준으로 좌/우 정렬해 공백을 채운다."""
    s = str(s)
    fill = max(0, width - _w(s))
    return (s + " " * fill) if align == "left" else (" " * fill + s)


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
    capacity_factor: float = 0.15      # 한국 태양광 이용률 ~13~15%
    lifetime_yr: int = 20
    discount_rate: float = 0.045
    kw_per_m2: float = 0.12            # 설치계수: 부지 1㎡당 설치가능 용량(kW)
    usable_land_ratio: float = 0.24    # 전체 부지 중 태양광 설치가능 비율
    #   근거: 한국에너지공단 산업단지 태양광 잠재량 분석
    #   (지붕면적=부지의 47.5% × 그중 설치가능 50% ≈ 0.24)


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
    land_area_m2: float = 0.0          # 자가발전 가용 부지면적(㎡). 0이면 자가발전 불가
    ets_covered: bool = False
    ppa_ceiling_ratio: float = 0.95
    ppa_position: Optional[float] = None
    ppa_available: bool = True         # 직접 PPA 현실적 접근성(법적 기준 아님)

    def __post_init__(self):
        if self.ppa_position is None:
            self.ppa_position = derive_ppa_position(self.annual_consumption_gwh)

    @property
    def direct_ppa_available(self) -> bool:
        return self.ppa_available

    def self_gen_coverage(self, pv: "PVParams") -> float:
        """가용 부지면적으로 충당 가능한 연간 수요 비율(0~1)."""
        if self.land_area_m2 <= 0:
            return 0.0
        usable_area = self.land_area_m2 * pv.usable_land_ratio
        capacity_kw = usable_area * pv.kw_per_m2
        annual_gen_kwh = capacity_kw * 8760 * pv.capacity_factor
        demand_kwh = self.annual_consumption_gwh * 1e6 * self.re_target_share
        if demand_kwh <= 0:
            return 0.0
        return min(1.0, annual_gen_kwh / demand_kwh)


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

    # 자가발전: 커버리지 비율로 혼합비용 산출
    coverage = firm.self_gen_coverage(pv)
    if coverage <= 0:
        self_gen = None
    else:
        lcoe = pv_lcoe(pv)
        # 나머지(1-coverage)를 채울 보완수단: 직접 PPA 가능하면 직접 PPA, 아니면 REC구매
        backup = direct if direct is not None else (m.industrial_tariff + m.rec_per_kwh)
        self_gen = coverage * lcoe + (1 - coverage) * backup

    total = {
        "녹색프리미엄": m.industrial_tariff + m.green_premium_adder,
        "REC 구매": m.industrial_tariff + m.rec_per_kwh,
        "제3자 PPA": ppa_e + m.non_energy_charge + m.network_charge_3rd,
        "직접 PPA": direct,
        "자가발전": self_gen,
    }
    if mode == "total":
        return total
    if mode == "premium":
        return {k: (v - m.industrial_tariff if v is not None else None) for k, v in total.items()}
    raise ValueError("mode must be 'total' or 'premium'")


def rank_costs(costs: dict) -> dict:
    valid = {k: v for k, v in costs.items() if v is not None}
    return {k: i + 1 for i, k in enumerate(sorted(valid, key=valid.get))}