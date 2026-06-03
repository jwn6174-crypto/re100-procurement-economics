"""
위험·적격성 보정 (Phase 3)
================================
비용 외 4개 기준을 점수화하고 가중합으로 종합순위를 산출.
  기준: 비용 / 가격안정성 / 계약유연성 / ETS적격성 / RE품질(Scope2)
  - 비용: Phase 1 총비용을 기업별 가용수단 내에서 정규화(최저=1, 최고=0)
  - 나머지 4개: 수단별 고정 점수(0~1, 높을수록 우수)
  - ETS적격성: ETS 비대상 기업은 이 기준 가중치를 0으로 두고 재정규화
  - 자가발전 점수 정밀화: 자가발전은 커버리지 비율만큼만 '순수 자가발전'이고
    나머지는 보완수단(직접 PPA, 없으면 REC)이므로, 기준점수도 비용처럼
    커버리지로 혼합한다. (보완수단이 고품질이라 실질 변화는 작지만, 'coverage 1.5%를
    100%처럼 만점 주는' 과대평가를 구조적으로 제거 → 결론이 점수 과대평가에 의존하지 않음을 보장)
가중치는 시나리오(비용중시/안정성중시/공급망대응)로 분기.
  ※ 현재 가중치는 잠정값. 논문에서는 전문가 쌍대비교 기반 AHP로 대체.
     ahp_weights()로 AHP 가중치 산출 가능(일관성비율 CR 포함).
"""
from math import prod
from cost_engine import MarketData, PVParams, cost_engine, rank_costs
from archetypes import ARCHETYPES, INSTRUMENTS

CRITERIA = ["비용", "가격안정성", "계약유연성", "ETS적격성", "RE품질"]

# 비용 외 4개 기준의 수단별 점수 (0~1, 높을수록 우수)
INSTRUMENT_SCORES = {
    "녹색프리미엄": {"가격안정성": 0.2, "계약유연성": 1.0, "ETS적격성": 0.0, "RE품질": 0.2},
    "REC 구매":     {"가격안정성": 0.4, "계약유연성": 0.8, "ETS적격성": 1.0, "RE품질": 0.6},
    "제3자 PPA":    {"가격안정성": 0.8, "계약유연성": 0.3, "ETS적격성": 1.0, "RE품질": 0.9},
    "직접 PPA":     {"가격안정성": 0.9, "계약유연성": 0.2, "ETS적격성": 1.0, "RE품질": 1.0},
    "자가발전":     {"가격안정성": 1.0, "계약유연성": 0.2, "ETS적격성": 1.0, "RE품질": 1.0},
}

# 시나리오별 가중치 (합=1). [TODO] 전문가 AHP로 교체.
SCENARIOS = {
    "비용중시":   {"비용": 0.50, "가격안정성": 0.15, "계약유연성": 0.10, "ETS적격성": 0.15, "RE품질": 0.10},
    "안정성중시": {"비용": 0.20, "가격안정성": 0.35, "계약유연성": 0.20, "ETS적격성": 0.15, "RE품질": 0.10},
    "공급망대응": {"비용": 0.20, "가격안정성": 0.15, "계약유연성": 0.05, "ETS적격성": 0.30, "RE품질": 0.30},
}

RI = {1: 0, 2: 0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32}


def ahp_weights(pairwise):
    """쌍대비교 행렬 → (가중치, 일관성비율 CR). 기하평균법."""
    n = len(pairwise)
    gm = [prod(row) ** (1 / n) for row in pairwise]
    s = sum(gm)
    w = [g / s for g in gm]
    aw = [sum(pairwise[i][j] * w[j] for j in range(n)) for i in range(n)]
    lam = sum(aw[i] / w[i] for i in range(n)) / n
    ci = (lam - n) / (n - 1) if n > 1 else 0
    cr = ci / RI[n] if RI.get(n) else 0
    return w, cr


def cost_scores(costs):
    """가용 수단 내에서 비용을 0~1로 정규화(최저비용=1)."""
    vals = {k: v for k, v in costs.items() if v is not None}
    lo, hi = min(vals.values()), max(vals.values())
    rng = hi - lo
    return {k: (1.0 if rng == 0 else (hi - v) / rng) for k, v in vals.items()}


def effective_weights(scenario, firm):
    """ETS 비대상이면 ETS적격성 가중치를 0으로 두고 재정규화."""
    w = dict(SCENARIOS[scenario])
    if not firm.ets_covered:
        w["ETS적격성"] = 0.0
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


def composite_scores(m, pv, firm, scenario):
    """수단별 종합점수(높을수록 우수). 가용 수단만.
    자가발전은 커버리지 비율만큼만 '순수 자가발전'이고 나머지는 보완수단이므로,
    기준점수도 비용처럼 혼합한다(커버리지×자가 + (1-커버리지)×보완수단).
    """
    costs = cost_engine(m, pv, firm, mode="total")
    cs = cost_scores(costs)
    w = effective_weights(scenario, firm)
    coverage = firm.self_gen_coverage(pv)
    backup = "직접 PPA" if costs.get("직접 PPA") is not None else "REC 구매"

    def criterion_score(inst, crit):
        base = INSTRUMENT_SCORES[inst][crit]
        if inst == "자가발전" and coverage < 1.0:
            # 자가발전 수단의 실질 점수 = 커버리지×자가 + (1-커버리지)×보완수단
            return coverage * base + (1 - coverage) * INSTRUMENT_SCORES[backup][crit]
        return base

    out = {}
    for s in INSTRUMENTS:
        if costs[s] is None:
            continue
        score = w["비용"] * cs[s]
        for c in ["가격안정성", "계약유연성", "ETS적격성", "RE품질"]:
            score += w[c] * criterion_score(s, c)
        out[s] = score
    return out


def composite_rank(scores):
    """종합점수 높은 순 1위."""
    return {k: i + 1 for i, k in enumerate(sorted(scores, key=scores.get, reverse=True))}


def scenario_matrix(scenario, m, pv):
    print(f"\n[종합순위 — {scenario}]  (1=최우수, x=불가)")
    header = "유형".ljust(22) + "".join(s[:6].rjust(11) for s in INSTRUMENTS)
    print(header)
    print("-" * len(header))
    for f in ARCHETYPES:
        cr_ = composite_rank(composite_scores(m, pv, f, scenario))
        row = f.name.ljust(20)
        for s in INSTRUMENTS:
            row += (str(cr_[s]) if s in cr_ else "x").rjust(11)
        print(row)


def flip_report(scenario, m, pv):
    """단가순위 → 종합순위 변동(역전) 요약."""
    print(f"\n[역전 분석 — {scenario}]  (단가순위 → 종합순위)")
    for f in ARCHETYPES:
        costs = cost_engine(m, pv, f, mode="total")
        cost_r = rank_costs(costs)
        comp_r = composite_rank(composite_scores(m, pv, f, scenario))
        flips = []
        for s in INSTRUMENTS:
            if s in cost_r and s in comp_r and comp_r[s] != cost_r[s]:
                arrow = "▲" if comp_r[s] < cost_r[s] else "▼"
                flips.append(f"{s} {cost_r[s]}→{comp_r[s]}{arrow}")
        tag = "  ETS대상" if f.ets_covered else ""
        print(f"  {f.name}{tag}")
        print(f"    {' · '.join(flips) if flips else '변동 없음'}")


if __name__ == "__main__":
    m = MarketData()
    pv = PVParams()
    print("=" * 66)
    print(" RE100 위험·적격성 보정 (Phase 3)")
    print("=" * 66)

    # AHP 함수 데모: 예시 쌍대비교 행렬의 가중치·CR
    demo = [
        [1, 3, 4, 3, 4],
        [1/3, 1, 2, 1, 2],
        [1/4, 1/2, 1, 1/2, 1],
        [1/3, 1, 2, 1, 2],
        [1/4, 1/2, 1, 1/2, 1],
    ]
    w, cr = ahp_weights(demo)
    print(" [AHP 데모] 예시 쌍대비교 → 가중치:",
          ", ".join(f"{c} {wi:.2f}" for c, wi in zip(CRITERIA, w)))
    print(f"            일관성비율 CR = {cr:.3f}  ({'합격' if cr < 0.1 else '불합격'}, 기준 0.1)")

    for sc in SCENARIOS:
        scenario_matrix(sc, m, pv)

    flip_report("공급망대응", m, pv)
    print("\n※ 가중치는 잠정값. 전문가 AHP 쌍대비교로 교체 예정.")