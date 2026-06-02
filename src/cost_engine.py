"""
RE100 이행수단 비용엔진 (Phase 1)
=====================================
기업 유형별 RE100 이행수단 경제성 비교 연구

각 이행수단을 동일 기준(₩/kWh, 균등화)으로 환산하는 비용엔진.
- 5개 수단: 녹색프리미엄 / REC 구매 / 제3자 PPA / 직접 PPA / 자가발전
- 모든 단가는 "기업이 RE100 대상 전력을 조달하는 데 드는 총비용(₩/kWh)"으로 통일
- PPA 단가는 단일값이 아니라 [SMP+REC(바닥) ~ 산업용요금×비율(천장)] 구간으로 처리

[기본값 출처 — 2025~2026 기준, 연구 시 최신값으로 갱신 필요]
  SMP                : 약 115 원/kWh (2026 초 육지 SMP 110원대 중반)
  REC                : 약 70,000 원/MWh = 70 원/kWh (RPS 현물 7만원 초반)
  녹색프리미엄 낙찰가 : 평균 약 11 원/kWh (하한 10원, '22 상반기 평균 10.9원)
  산업용 전기요금     : 약 179 원/kWh (2025 상반기 산업용 평균, 계약종별로 갱신 필요)
  태양광 CAPEX/O&M    : 예시값 — 사업자 견적·KEEI LCOE 자료로 교체 권장
"""

from dataclasses import dataclass


@dataclass
class MarketData:
    """공개 시장 데이터 (₩/kWh 단위로 통일)."""
    smp: float = 115.0                 # 계통한계가격
    rec_per_kwh: float = 70.0          # REC 단가 (70,000원/MWh → 70원/kWh)
    green_premium_adder: float = 11.0  # 녹색프리미엄 평균 낙찰가 (요금에 가산)
    industrial_tariff: float = 179.0   # 산업용 전기요금 (전력량+기본+기후환경 포함 평균)

    # PPA 부가비용 (제도별 차이 — 연구의 핵심 차별 요소)
    network_charge_3rd: float = 25.0   # 제3자 PPA 망 이용료 (의무) — 예시값
    network_charge_direct: float = 8.0 # 직접 PPA 망 이용료 (선택·일부 면제) — 예시값
    transaction_fee_direct: float = 0.0  # 직접 PPA 거래수수료 (3년 면제 가정)


@dataclass
class PVParams:
    """자가발전(태양광) LCOE 산정 파라미터."""
    capex_per_kw: float = 1_300_000.0  # 설치단가 (원/kW)
    om_per_kw_yr: float = 35_000.0     # 연간 운영비 (원/kW)
    capacity_factor: float = 0.15      # 이용률 (국내 태양광 약 15%)
    lifetime_yr: int = 20              # 수명
    discount_rate: float = 0.045       # 할인율


@dataclass
class FirmProfile:
    """기업 아키타입 입력값 (Phase 2에서 유형별로 채움)."""
    name: str
    annual_consumption_gwh: float      # 연간 전력 소비량
    re_target_share: float = 1.0       # RE100 충당 비율 (1.0 = 100%)
    has_land: bool = True              # 부지/지붕 보유 여부 (자가발전 가능성)
    ppa_ceiling_ratio: float = 0.95    # PPA 단가 천장 = 산업용요금 × 비율
    ppa_position: float = 0.5          # PPA 단가 위치 (0=바닥 SMP+REC, 1=천장)


def crf(rate: float, n: int) -> float:
    """자본회수계수 (Capital Recovery Factor)."""
    return rate * (1 + rate) ** n / ((1 + rate) ** n - 1)


def pv_lcoe(pv: PVParams) -> float:
    """태양광 자가발전 LCOE (₩/kWh). 발전량 1kW 기준이면 단가는 용량과 무관."""
    annualized_capex = pv.capex_per_kw * crf(pv.discount_rate, pv.lifetime_yr)
    annual_gen_kwh = 8760 * pv.capacity_factor   # 1kW당 연간 발전량
    return (annualized_capex + pv.om_per_kw_yr) / annual_gen_kwh


def ppa_bounds(m: MarketData, firm: FirmProfile):
    """PPA 전력량요금의 경제적 바닥·천장 (₩/kWh)."""
    floor = m.smp + m.rec_per_kwh                       # 발전사업자 기회비용
    ceiling = m.industrial_tariff * firm.ppa_ceiling_ratio  # 구매자 수용 상한
    return floor, ceiling


def ppa_energy_price(m: MarketData, firm: FirmProfile) -> float:
    """구간 내 위치(ppa_position)로 PPA 전력량요금 결정."""
    floor, ceiling = ppa_bounds(m, firm)
    return floor + (ceiling - floor) * firm.ppa_position


def cost_engine(m: MarketData, pv: PVParams, firm: FirmProfile) -> dict:
    """5개 이행수단의 RE100 조달 단가 (₩/kWh)를 반환."""
    ppa_e = ppa_energy_price(m, firm)

    costs = {
        # 기존 요금 + 녹색프리미엄 가산
        "녹색프리미엄": m.industrial_tariff + m.green_premium_adder,
        # 전력은 한전(요금) + REC 별도 구매
        "REC 구매": m.industrial_tariff + m.rec_per_kwh,
        # PPA 전력량요금 + 망 이용료(의무)
        "제3자 PPA": ppa_e + m.network_charge_3rd,
        # PPA 전력량요금 + 망 이용료(경감) + 수수료(면제)
        "직접 PPA": ppa_e + m.network_charge_direct + m.transaction_fee_direct,
    }
    # 자가발전은 부지 보유 시에만 가능
    costs["자가발전"] = pv_lcoe(pv) if firm.has_land else None
    return costs


def rank_costs(costs: dict) -> dict:
    """단가 기준 순위 (1=최저가). None(불가능)은 제외."""
    valid = {k: v for k, v in costs.items() if v is not None}
    order = sorted(valid, key=valid.get)
    return {k: i + 1 for i, k in enumerate(order)}


def report(firm: FirmProfile, m: MarketData, pv: PVParams):
    costs = cost_engine(m, pv, firm)
    ranks = rank_costs(costs)
    floor, ceiling = ppa_bounds(m, firm)

    print(f"\n■ 아키타입: {firm.name}")
    print(f"  소비 {firm.annual_consumption_gwh} GWh/yr · "
          f"부지 {'있음' if firm.has_land else '없음'} · "
          f"RE 충당 {firm.re_target_share:.0%}")
    print(f"  PPA 단가구간: {floor:.0f} ~ {ceiling:.0f} 원/kWh "
          f"(위치 {firm.ppa_position:.0%} → {ppa_energy_price(m, firm):.0f}원)")
    print(f"  {'-'*42}")
    print(f"  {'수단':<12}{'단가(원/kWh)':>14}{'순위':>8}")
    print(f"  {'-'*42}")
    for k, v in costs.items():
        if v is None:
            print(f"  {k:<12}{'N/A (부지없음)':>14}{'-':>8}")
        else:
            print(f"  {k:<12}{v:>14.1f}{ranks[k]:>8}")


if __name__ == "__main__":
    market = MarketData()
    pv = PVParams()

    archetypes = [
        FirmProfile("전력다소비·부지보유·ETS 제조", 500.0, has_land=True, ppa_position=0.45),
        FirmProfile("대규모·부지보유·비ETS 데이터센터", 300.0, has_land=True, ppa_position=0.40),
        FirmProfile("저소비·무부지·비ETS 서비스업", 5.0, has_land=False, ppa_position=0.70),
    ]

    print("=" * 46)
    print(" RE100 비용엔진 — 단가 기준 비교 (Phase 1)")
    print(f" SMP {market.smp} · REC {market.rec_per_kwh} · "
          f"녹색프리미엄 +{market.green_premium_adder} · 산업용 {market.industrial_tariff}")
    print(f" 태양광 LCOE = {pv_lcoe(pv):.1f} 원/kWh")
    print("=" * 46)

    for a in archetypes:
        report(a, market, pv)

    print("\n※ 모든 기본값은 예시이며, 연구 시 최신 공개데이터로 갱신해야 함.")
    print("※ 본 단계는 '단가 기준' 순위. 위험·적격성 보정은 Phase 3.")