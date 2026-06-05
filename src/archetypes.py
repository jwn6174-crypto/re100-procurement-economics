"""
기업 아키타입 정의 (Phase 2 · v2)
================================
3축으로 6개 대표 유형(업종+규모)을 정의:
  - 소비규모   : annual_consumption_gwh
  - ETS 편입   : ets_covered
  - 자가발전 커버리지 : land_area_m2(가용 부지면적)와 수요로 cost_engine이 산출

값의 근거·출처:
  - 소비규모 상대순위: 한전 업종별 전력사용량(전력데이터개방포털, 2026.3)
      영상·음향(반도체) > 1차금속(철강)·화학(석유화학) > 자동차 > 서비스.
      ※ 절대 GWh 값은 대표 대기업 스케일의 임시 추정치(평균의 함정 때문에 순위만 데이터 근거).
  - ETS: 배출권거래법 제8조(업체 125k/사업장 25k tCO2 문턱). 현대차=대상(감사보고서 확인).
      데이터센터·서비스 중소는 직접배출 작아 비대상.
  - 부지면적(land_area_m2): 대표 기업 공개 자료 기반.
      포스코 포항9.5M+광양21.35M=30.85M㎡ / 현대차 울산5M+아산1.83M+전주0.5M=7.33M㎡ /
      LG화학 여수2.9M+대산1.3M+파주0.39M=4.59M㎡ / SK하이닉스 이천0.96M+청주0.96M(이천 동급 프록시)=1.92M㎡.
      데이터센터·중소 제조 부지는 추정값(공개 자료 없음).
  - 가용부지 비율(usable_land_ratio=0.24)·설치계수·이용률: cost_engine, 한국에너지공단/표준값.
  - 서비스 중소 직접 PPA 'ppa_available=False'는 법적 금지가 아니라 현실적 접근성 가정.
      유형 정의 = 임차 점포 기반 영세 서비스·소매(부지 0).
"""
from cost_engine import MarketData, PVParams, FirmProfile, cost_engine, rank_costs, pv_lcoe, pad, _w

# 안 A + 중소 제조 = 7개 유형 (업종+규모). 부지면적은 대표기업 공개값(추정 표시).
ARCHETYPES = [
    FirmProfile("반도체 대기업",        5000.0, sector="반도체",
                land_area_m2=1_920_000, ets_covered=True,  ppa_available=True),
    FirmProfile("철강 대기업",          4000.0, sector="철강",
                land_area_m2=30_850_000, ets_covered=True, ppa_available=True),
    FirmProfile("석유화학 대기업",      3500.0, sector="석유화학",
                land_area_m2=4_587_561, ets_covered=True, ppa_available=True),
    FirmProfile("자동차 완성차 대기업",  2000.0, sector="자동차",
                land_area_m2=7_327_348, ets_covered=True, ppa_available=True),
    FirmProfile("데이터센터",           1500.0, sector="데이터센터",
                land_area_m2=100_000,  ets_covered=False, ppa_available=True),
    FirmProfile("중소 제조(부품)",          5.0, sector="자동차부품",
                land_area_m2=30_000,   ets_covered=False, ppa_available=True),
    FirmProfile("영세 서비스·소매",         3.0, sector="서비스",
                land_area_m2=0,        ets_covered=False, ppa_available=False),
]

INSTRUMENTS = ["녹색프리미엄", "REC 구매", "제3자 PPA", "직접 PPA", "자가발전"]


def ranking_matrix(archetypes, m, pv, mode="total"):
    print(f"\n[순위 매트릭스 — {mode} 기준]  (1=최저비용, x=불가)")
    NAME_W, COL_W = 24, 11
    header = pad("유형", NAME_W) + "".join(pad(s[:6], COL_W, "right") for s in INSTRUMENTS)
    print(header)
    print("-" * _w(header))
    for f in archetypes:
        costs = cost_engine(m, pv, f, mode=mode)
        ranks = rank_costs(costs)
        row = pad(f.name, NAME_W)
        for s in INSTRUMENTS:
            cell = "x" if costs[s] is None else str(ranks[s])
            row += pad(cell, COL_W, "right")
        print(row)


def attribute_table(archetypes, pv):
    print("\n[아키타입 속성]")
    NAME_W = 24
    print(pad("유형", NAME_W) + pad("소비(GWh)", 11, "right") + pad("ETS", 8, "right")
          + pad("자가커버", 11, "right") + pad("직접PPA", 10, "right") + pad("PPA위치", 10, "right"))
    for f in archetypes:
        cov = f.self_gen_coverage(pv)
        print(pad(f.name, NAME_W)
              + pad(f"{f.annual_consumption_gwh:.0f}", 11, "right")
              + pad("대상" if f.ets_covered else "비대상", 8, "right")
              + pad(f"{cov*100:.1f}%", 11, "right")
              + pad("가능" if f.direct_ppa_available else "불가", 10, "right")
              + pad(f"{f.ppa_position:.2f}", 10, "right"))


if __name__ == "__main__":
    m = MarketData()
    pv = PVParams()
    print("=" * 64)
    print(" RE100 아키타입 비교 (Phase 2 · v2, 안A+중소제조 7유형)")
    print(f" 태양광 LCOE = {pv_lcoe(pv):.1f} 원/kWh")
    print("=" * 64)
    attribute_table(ARCHETYPES, pv)
    ranking_matrix(ARCHETYPES, m, pv, mode="total")
    print("\n※ 자가발전은 커버리지 비율로 혼합비용 산출(부지면적+수요).")
    print("※ 소비규모 순위는 한전 데이터 근거, 절대값·부지면적은 임시값.")