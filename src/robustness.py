"""
강건성 검증 (Phase 4)
================================
검증 대상(주장 A): 공급망대응 시나리오에서 ETS 기업(반도체·철강)은
                   직접 PPA가 1~2위다.
세 가지 방법:
  1) 몬테카를로 : 입력(시장가·점수·가중치)을 분포로 수천 번 흔들어 주장 유지 확률
  2) 토네이도   : 입력을 하나씩 극단까지 밀어 직접PPA 순위가 어디까지 흔들리나
  3) (임계점)   : 다음 단계
※ ETS적격성은 0/1 이진이라 흔들지 않음. RE품질은 잠정 연속값(Scope2 체크리스트로 교체 예정).
"""
import random
from copy import deepcopy
from cost_engine import MarketData, PVParams, cost_engine
from archetypes import ARCHETYPES, INSTRUMENTS
from scoring import INSTRUMENT_SCORES, SCENARIOS, cost_scores, composite_rank

NONCOST = ["가격안정성", "계약유연성", "ETS적격성", "RE품질"]
ETS_FIRMS = [f for f in ARCHETYPES if f.ets_covered]


def eff_weights(weights, firm):
    w = dict(weights)
    if not firm.ets_covered:
        w["ETS적격성"] = 0.0
    tot = sum(w.values())
    return {k: v / tot for k, v in w.items()}


def composite(m, pv, firm, weights, scores):
    costs = cost_engine(m, pv, firm, "total")
    cs = cost_scores(costs)
    out = {}
    for s in INSTRUMENTS:
        if costs[s] is None:
            continue
        val = weights["비용"] * cs[s]
        for c in NONCOST:
            val += weights[c] * scores[s][c]
        out[s] = val
    return out


def direct_ppa_rank(m, pv, firm, weights, scores):
    r = composite_rank(composite(m, pv, firm, eff_weights(weights, firm), scores))
    return r.get("직접 PPA", 99)


# ---------- 1) 몬테카를로 ----------
def perturb_market(rng):
    m = MarketData()
    m.smp *= rng.uniform(0.85, 1.15)
    m.rec_per_kwh *= rng.uniform(0.60, 1.20)
    m.green_premium_adder *= rng.uniform(0.80, 1.50)
    m.industrial_tariff *= rng.uniform(0.92, 1.08)
    m.industrial_energy_charge *= rng.uniform(0.85, 1.15)
    m.network_charge_3rd *= rng.uniform(0.70, 1.30)
    m.network_charge_direct *= rng.uniform(0.70, 1.30)
    return m


def perturb_pv(rng):
    pv = PVParams()
    pv.capex_per_kw *= rng.uniform(0.85, 1.15)
    pv.capacity_factor *= rng.uniform(0.90, 1.10)
    return pv


def perturb_scores(rng):
    s = deepcopy(INSTRUMENT_SCORES)
    for k in s:
        for c in s[k]:
            if c == "ETS적격성":      # 이진 — 흔들지 않음
                continue
            s[k][c] = min(1.0, max(0.0, s[k][c] + rng.uniform(-0.15, 0.15)))
    return s


def perturb_weights(base, rng):
    w = {k: max(0.01, v * rng.uniform(0.6, 1.4)) for k, v in base.items()}
    tot = sum(w.values())
    return {k: v / tot for k, v in w.items()}


def monte_carlo(n=5000, scenario="공급망대응", seed=42):
    rng = random.Random(seed)
    hold = {f.name: 0 for f in ETS_FIRMS}
    for _ in range(n):
        m, pv = perturb_market(rng), perturb_pv(rng)
        sc = perturb_scores(rng)
        w = perturb_weights(SCENARIOS[scenario], rng)
        for f in ETS_FIRMS:
            if direct_ppa_rank(m, pv, f, w, sc) <= 2:
                hold[f.name] += 1
    return {k: v / n for k, v in hold.items()}


# ---------- 2) 토네이도 ----------
def tornado(firm, scenario="공급망대응"):
    base_w = SCENARIOS[scenario]
    rows = []

    def rank_with(m=None, pv=None, w=None, sc=None):
        return direct_ppa_rank(m or MarketData(), pv or PVParams(), firm,
                               w or base_w, sc or INSTRUMENT_SCORES)

    # REC 가격
    lo, hi = MarketData(), MarketData()
    lo.rec_per_kwh *= 0.5; hi.rec_per_kwh *= 1.5
    rows.append(("REC 가격 ±50%", rank_with(m=lo), rank_with(m=hi)))
    # SMP
    lo, hi = MarketData(), MarketData()
    lo.smp *= 0.7; hi.smp *= 1.3
    rows.append(("SMP ±30%", rank_with(m=lo), rank_with(m=hi)))
    # RE품질 가중치
    lo = dict(base_w); hi = dict(base_w)
    lo["RE품질"] *= 0.3; hi["RE품질"] *= 1.7
    rows.append(("RE품질 가중치 ±", rank_with(w=lo), rank_with(w=hi)))
    # ETS 가중치
    lo = dict(base_w); hi = dict(base_w)
    lo["ETS적격성"] *= 0.3; hi["ETS적격성"] *= 1.7
    rows.append(("ETS 가중치 ±", rank_with(w=lo), rank_with(w=hi)))
    # 비용 가중치
    lo = dict(base_w); hi = dict(base_w)
    lo["비용"] *= 0.5; hi["비용"] *= 2.0
    rows.append(("비용 가중치 ±", rank_with(w=lo), rank_with(w=hi)))
    # 직접 PPA 망 이용료
    lo, hi = MarketData(), MarketData()
    lo.network_charge_direct *= 0.5; hi.network_charge_direct *= 2.0
    rows.append(("직접PPA 망요금 ±", rank_with(m=lo), rank_with(m=hi)))
    return rows


if __name__ == "__main__":
    print("=" * 62)
    print(" 강건성 검증 (Phase 4) — 주장 A: ETS 기업 직접 PPA 1~2위")
    print("=" * 62)

    print("\n[기준점 — 흔들기 전]")
    for f in ETS_FIRMS:
        print(f"  {f.name}: 직접 PPA = {direct_ppa_rank(MarketData(), PVParams(), f, SCENARIOS['공급망대응'], INSTRUMENT_SCORES)}위")

    print("\n[1) 몬테카를로 — 5000회, 직접 PPA가 1~2위일 확률]")
    for name, p in monte_carlo().items():
        bar = "█" * round(p * 30)
        print(f"  {name:<22}{p*100:5.1f}%  {bar}")

    print("\n[2) 토네이도 — 철강·석유화학, 입력별 직접PPA 순위 (저←→고)]")
    for label, lo_r, hi_r in tornado(ETS_FIRMS[1]):
        flag = "" if max(lo_r, hi_r) <= 2 else "  ← 1~2위 이탈!"
        print(f"  {label:<18} {lo_r} ~ {hi_r}위{flag}")

    print("\n※ ETS적격성은 0/1 이진이라 미교란. RE품질은 Scope2 체크리스트로 교체 예정.")