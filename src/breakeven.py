"""
임계점(breakeven) 분석 (Phase 4 완결)
========================================
"정확히 어디서 주장 A가 무너지는가"를 찾는다.
  (1) 관점 이동: 공급망대응 → 비용중시로 가중치를 섞을 때, 직접 PPA가 3위로
                떨어지는 혼합 비율 t* (t=0 공급망대응, t=1 비용중시)
  (2) RE품질 가중치를 얼마까지 낮추면 무너지나
  (3) REC 가격 변화에 따른 직접 PPA 순위 (낮을수록 PPA에 유리해지는 역설 확인)
대상: 철강·석유화학(ETS, 모든 수단 가용) — 두 ETS 기업 중 더 취약한 쪽.
"""
from cost_engine import MarketData, PVParams
from scoring import SCENARIOS, INSTRUMENT_SCORES
from robustness import direct_ppa_rank, ETS_FIRMS

FIRM = ETS_FIRMS[1]  # 철강·석유화학


def blend(a, b, t):
    return {k: a[k] * (1 - t) + b[k] * t for k in a}


def breakeven_shift():
    a, b = SCENARIOS["공급망대응"], SCENARIOS["비용중시"]
    for i in range(101):
        t = i / 100
        if direct_ppa_rank(MarketData(), PVParams(), FIRM, blend(a, b, t), INSTRUMENT_SCORES) > 2:
            return t, blend(a, b, t)
    return None, None


def breakeven_requality():
    base = SCENARIOS["공급망대응"]
    for i in range(101):
        f = 1 - i / 100               # 1.0 → 0.0
        w = dict(base); w["RE품질"] *= f
        if direct_ppa_rank(MarketData(), PVParams(), FIRM, w, INSTRUMENT_SCORES) > 2:
            return f, base["RE품질"] * f
    return None, None


def rec_sweep():
    out = []
    for rec in [30, 50, 70, 90, 110]:
        m = MarketData(); m.rec_per_kwh = rec
        r = direct_ppa_rank(m, PVParams(), FIRM, SCENARIOS["공급망대응"], INSTRUMENT_SCORES)
        out.append((rec, r))
    return out


if __name__ == "__main__":
    print("=" * 60)
    print(" 임계점 분석 (Phase 4 완결) — 대상: 철강·석유화학")
    print("=" * 60)

    t, w = breakeven_shift()
    print("\n[1] 관점 이동: 공급망대응(0) → 비용중시(1)")
    if t is None:
        print("    전 구간에서 직접 PPA가 1~2위 유지 (관점 이동만으론 안 깨짐)")
    else:
        print(f"    t = {t:.2f} 지점에서 직접 PPA가 3위로 하락")
        print(f"    → 이때 가중치: 비용 {w['비용']:.2f}, ETS {w['ETS적격성']:.2f}, "
              f"RE품질 {w['RE품질']:.2f}")
        print(f"    해석: 비용을 이만큼 중시하는 쪽으로 {t*100:.0f}% 이동해야 무너짐")

    f, val = breakeven_requality()
    print("\n[2] RE품질 가중치 낮추기 (기준 0.30)")
    if f is None:
        print("    0까지 낮춰도 직접 PPA 1~2위 유지")
    else:
        print(f"    RE품질 가중치를 {val:.3f}(기준의 {f*100:.0f}%)까지 낮추면 3위로 하락")

    print("\n[3] REC 가격별 직접 PPA 순위 (공급망대응)")
    for rec, r in rec_sweep():
        print(f"    REC {rec}원/kWh → 직접 PPA {r}위")
    print("    (REC가 낮아져도 순위 유지/개선 — PPA 단가가 싸지므로 오히려 유리)")