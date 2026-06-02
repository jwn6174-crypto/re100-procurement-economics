"""
RE100 이행수단 비용엔진 (Phase 1 · v2)
==========================================
기업 유형별 RE100 이행수단 경제성 비교 연구

각 이행수단을 동일 기준(원/kWh)으로 환산하는 비용엔진.
5개 수단: 녹색프리미엄 / REC 구매 / 제3자 PPA / 직접 PPA / 자가발전

[v2 변경점]
1) 두 모드 지원
   - total   : RE100 전력 1kWh 조달에 드는 '총비용'
   - premium : 재생에너지 속성을 위해 '추가로' 내는 비용 (= total - 일반 산업용요금)
               음수면 일반 계통전력보다 싸다는 의미(예: 자가발전)
2) PPA 천장을 산업용 '전력량요금'(에너지 부분)으로 재설정
   - 기존엔 올인 평균요금(기본+기후환경 포함)을 천장으로 잡아 비교가 부정확했음
3) PPA는 전력량요금을 대체하되 비에너지 요금(기본요금 등)은 그대로 부담한다고 모델링
4) 현재 고REC 국면에서 PPA 바닥(SMP+REC) > 천장이 되는 '역전'을 명시적으로 처리

[기본값 출처 — 2025~2026 기준, 연구 시 최신값으로 갱신 필요]
  SMP            : 약 115 원/kWh
  REC            : 약 70 원/kWh (70,000원/MWh)
  녹색프리미엄    : 평균 약 11 원/kWh (요금에 가산, 하한 10원)
  산업용 올인요금 : 약 179 원/kWh (기본+전력량+기후환경 포함 평균)
  산업용 전력량요금: 약 120 원/kWh (에너지 부분만 — 계약종별·계절·시간대로 갱신 필요)
  태양광 CAPEX/O&M: 예시값 — 사업자 견적·KEEI LCOE 자료로 교체 권장
"""

from dataclasses import dataclass


@dataclass
class MarketData:
    """공개 시장 데이터 (원/kWh)."""
    smp: float = 115.0                   # 계통한계가격
    rec_per_kwh: float = 70.0            # REC 단가
    green_premium_adder: float = 11.0    # 녹색프리미엄 평균 낙찰가
    industrial_tariff: float = 179.0     # 산업용 올인 평균요금
    industrial_energy_charge: float = 120.0  # 산업용 전력량요금(에너지 부분만)

    network_charge_3rd: float = 25.0     # 제3자 PPA 망 이용료(의무) — 예시값
    network_charge_direct: float = 8.0   # 직접 PPA 망 이용료(경감) — 예시값
    transaction_fee_direct: float = 0.0  # 직접 PPA 거래수수료(3년 면제 가정)

    @property
    def non_energy_charge(self) -> float:
        """비에너지 요금(기본요금+기후환경 등). PPA에서도 그대로 부담."""
        return self.industrial_tariff - self.industrial_energy_charge


@dataclass
class PVParams:
    """자가발전(태양광) LCOE 파라미터."""
    capex_per_kw: float = 1_300_000.0
    om_per_kw_yr: float = 35_000.0
    capacity_factor: float = 0.15
    lifetime_yr: int = 20
    discount_rate: float = 0.045


@dataclass
class FirmProfile:
    """기업 아키타입 (Phase 2에서 유형별로 채움)."""
    name: str
    annual_consumption_gwh: float
    re_target_share: float = 1.0
    has_land: bool = True
    ppa_ceiling_ratio: float = 0.95   # PPA 천장 = 전력량요금 × 비율
    ppa_position: float = 0.5         # 구간 내 위치(0=바닥, 1=천장)


def crf(rate: float, n: int) -> float:
    """자본회수계수."""
    return rate * (1 + rate) ** n / ((1 + rate) ** n - 1)


def pv_lcoe(pv: PVParams) -> float:
    """태양광 LCOE (원/kWh)."""
    annualized_capex = pv.capex_per_kw * crf(pv.discount_rate, pv.lifetime_yr)
    annual_gen_kwh = 8760 * pv.capacity_factor
    return (annualized_capex + pv.om_per_kw_yr) / annual_gen_kwh


def ppa_bounds(m: MarketData, firm: FirmProfile):
    """PPA 전력량요금의 바닥·천장 (원/kWh)."""
    floor = m.smp + m.rec_per_kwh                          # 발전사업자 기회비용(하한)
    ceiling = m.industrial_energy_charge * firm.ppa_ceiling_ratio  # 구매자 전력량요금 기준
    return floor, ceiling


def ppa_energy_price(m: MarketData, firm: FirmProfile):
    """PPA 전력량요금 결정. (가격, 역전여부) 반환.
    역전(바닥>천장): 현재 고REC 국면에서 발전사업자 기회비용이 구매자 전력량요금을
    초과 → PPA는 바닥(SMP+REC)에서 체결되고, 번들된 REC 가치로 경쟁한다고 본다."""
    floor, ceiling = ppa_bounds(m, firm)
    if floor < ceiling:
        return floor + (ceiling - floor) * firm.ppa_position, False
    return floor, True


def cost_engine(m: MarketData, pv: PVParams, firm: FirmProfile, mode: str = "total") -> dict:
    """5개 수단의 단가(원/kWh) 반환.
    mode='total'  : 총 조달비용
    mode='premium': 증분비용 = total - 일반 산업용요금"""
    ppa_e, _ = ppa_energy_price(m, firm)

    total = {
        "녹색프리미엄": m.industrial_tariff + m.green_premium_adder,
        "REC 구매": m.industrial_tariff + m.rec_per_kwh,
        # PPA: 전력량요금 대체(ppa_e) + 비에너지 요금 그대로 + 망 이용료
        "제3자 PPA": ppa_e + m.non_energy_charge + m.network_charge_3rd,
        "직접 PPA": ppa_e + m.non_energy_charge + m.network_charge_direct + m.transaction_fee_direct,
        "자가발전": pv_lcoe(pv) if firm.has_land else None,
    }
    if mode == "total":
        return total
    if mode == "premium":
        # 반사실(counterfactual): RE100 안 하고 일반 계통전력을 산업용요금에 구매
        return {k: (v - m.industrial_tariff if v is not None else None) for k, v in total.items()}
    raise ValueError("mode must be 'total' or 'premium'")


def rank_costs(costs: dict) -> dict:
    """단가 기준 순위(1=최저). None 제외."""
    valid = {k: v for k, v in costs.items() if v is not None}
    order = sorted(valid, key=valid.get)
    return {k: i + 1 for i, k in enumerate(order)}


def report(firm: FirmProfile, m: MarketData, pv: PVParams):
    total = cost_engine(m, pv, firm, mode="total")
    premium = cost_engine(m, pv, firm, mode="premium")
    rank_t = rank_costs(total)
    floor, ceiling = ppa_bounds(m, firm)
    ppa_e, inverted = ppa_energy_price(m, firm)

    print(f"\n■ {firm.name}")
    print(f"  소비 {firm.annual_consumption_gwh} GWh/yr · 부지 {'있음' if firm.has_land else '없음'}")
    note = "  ※ 바닥>천장 역전 → PPA는 바닥(SMP+REC)에서 체결" if inverted else ""
    print(f"  PPA 전력량요금: 바닥 {floor:.0f} / 천장 {ceiling:.0f} → 적용 {ppa_e:.0f}원{note}")
    print(f"  {'-'*52}")
    print(f"  {'수단':<10}{'총비용':>12}{'증분비용':>12}{'총비용순위':>12}")
    print(f"  {'-'*52}")
    for k in total:
        if total[k] is None:
            print(f"  {k:<10}{'N/A':>12}{'N/A':>12}{'-':>12}")
        else:
            print(f"  {k:<10}{total[k]:>12.1f}{premium[k]:>+12.1f}{rank_t[k]:>12}")


if __name__ == "__main__":
    market = MarketData()
    pv = PVParams()

    archetypes = [
        FirmProfile("전력다소비·부지보유·ETS 제조", 500.0, has_land=True, ppa_position=0.45),
        FirmProfile("대규모·부지보유·비ETS 데이터센터", 300.0, has_land=True, ppa_position=0.40),
        FirmProfile("저소비·무부지·비ETS 서비스업", 5.0, has_land=False, ppa_position=0.70),
    ]

    print("=" * 56)
    print(" RE100 비용엔진 v2 — 총비용 / 증분비용 (Phase 1)")
    print(f" SMP {market.smp} · REC {market.rec_per_kwh} · 녹색프리미엄 +{market.green_premium_adder}")
    print(f" 산업용 올인 {market.industrial_tariff} · 전력량요금 {market.industrial_energy_charge}"
          f" · 비에너지 {market.non_energy_charge:.0f}")
    print(f" 태양광 LCOE = {pv_lcoe(pv):.1f} 원/kWh")
    print("=" * 56)
    print(" * 증분비용: 일반 산업용요금 대비 추가비용. 음수=계통보다 저렴.")

    for a in archetypes:
        report(a, market, pv)

    print("\n※ 기본값은 예시. 연구 시 최신 공개데이터로 갱신.")
    print("※ 단가 기준 순위임. 위험·적격성 보정은 Phase 3.")