"""
기업 아키타입 정의 (Phase 2)
================================
3축으로 5개 대표 유형을 정의:
  - 소비규모   : annual_consumption_gwh (한전 업종별 전력사용량으로 갱신)
  - 부지 보유  : has_land (업종 대리변수)
  - ETS 편입   : ets_covered (온실가스종합정보센터 할당명단)

※ 소비규모 값은 현재 '자릿수만 현실적인' 임시값. 한전 데이터로 교체 필요.
"""
from cost_engine import MarketData, PVParams, FirmProfile, cost_engine, rank_costs, pv_lcoe

# [TODO] annual_consumption_gwh는 한전 업종별 전력사용량(÷고객호수)으로 교체
ARCHETYPES = [
    FirmProfile("반도체·디스플레이 대기업", 5000.0, sector="반도체",       has_land=False, ets_covered=True),
    FirmProfile("철강·석유화학 대기업",     4000.0, sector="철강석유화학", has_land=True,  ets_covered=True),
    FirmProfile("자동차·기계 중견 제조",     150.0, sector="자동차기계",   has_land=True,  ets_covered=False),
    FirmProfile("데이터센터",                200.0, sector="데이터센터",   has_land=True,  ets_covered=False),
    FirmProfile("의류·유통·서비스 중소",       5.0, sector="서비스",       has_land=False, ets_covered=False),
]

INSTRUMENTS = ["녹색프리미엄", "REC 구매", "제3자 PPA", "직접 PPA", "자가발전"]


def ranking_matrix(archetypes, m, pv, mode="total"):
    print(f"\n[순위 매트릭스 — {mode} 기준]  (1=최저비용, x=불가)")
    header = "유형".ljust(22) + "".join(s[:6].rjust(11) for s in INSTRUMENTS)
    print(header)
    print("-" * len(header))
    for f in archetypes:
        costs = cost_engine(m, pv, f, mode=mode)
        ranks = rank_costs(costs)
        row = f.name.ljust(20)
        for s in INSTRUMENTS:
            cell = "x" if costs[s] is None else str(ranks[s])
            row += cell.rjust(11)
        print(row)


def attribute_table(archetypes):
    print("\n[아키타입 속성]")
    print("유형".ljust(22) + "소비(GWh)".rjust(11) + "부지".rjust(7)
          + "ETS".rjust(7) + "직접PPA".rjust(9) + "PPA위치".rjust(9))
    for f in archetypes:
        print(f.name.ljust(20)
              + f"{f.annual_consumption_gwh:>11.0f}"
              + ("있음" if f.has_land else "없음").rjust(6)
              + ("대상" if f.ets_covered else "비대상").rjust(6)
              + ("가능" if f.direct_ppa_available else "불가").rjust(8)
              + f"{f.ppa_position:>9.2f}")


if __name__ == "__main__":
    m = MarketData()
    pv = PVParams()
    print("=" * 60)
    print(" RE100 아키타입 비교 (Phase 2)")
    print(f" 태양광 LCOE = {pv_lcoe(pv):.1f} 원/kWh")
    print("=" * 60)
    attribute_table(ARCHETYPES)
    ranking_matrix(ARCHETYPES, m, pv, mode="total")
    ranking_matrix(ARCHETYPES, m, pv, mode="premium")
    print("\n※ 소비규모는 임시값. 한전 업종별 전력사용량으로 교체 필요.")
    print("※ 단가 기준 순위. ETS 적격성·위험 보정은 Phase 3.")