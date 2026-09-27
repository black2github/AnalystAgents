"""Хост-приёмка калибровок HOOD/RKLB (пакет HOOD_RKLB_Calibrations_v1): шаги 1–5 последовательности IMMA §9.
1) RV-прогон reverse_valuation по <TK>_calibration_v1.0.yaml (сайдкар, save) → implied CAGR, TV share, класс;
2) валидатор режим calibration (схема v1.0.1, MC-G5-001..013 по измеренной σ, сухой прогон, дисперсия intrinsic/full);
Печатает сводку; нормативные 500k-прогоны запускаются отдельно (--mc) только если шаги 1–2 pass."""
import json
import sys
import urllib.request
from pathlib import Path

import yaml

WS = Path("C:/openclaw-lab/data/workspace-invest"); PK = WS / "from_imma" / "HOOD_RKLB_Calibrations_v1"
URL = "http://127.0.0.1:18791/run"; TODAY = "2026-09-23"
TKS = [a for a in sys.argv[1:] if a in ("HOOD", "RKLB")] or ["HOOD", "RKLB"]
MC = "--mc" in sys.argv
FOLDER = {"HOOD": "hood", "RKLB": "rklb"}


def post(payload: dict) -> dict:
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        return json.load(r)


def rv_inputs(tk: str) -> dict:
    f = yaml.safe_load((PK / f"{tk}_calibration_v1.0.yaml").read_text(encoding="utf-8"))["calibration_v1.0"]
    m, bs, bp = f["market"], f["balance_sheet"], f["base_period"]
    cash = bs.get("cash", bs.get("cash_and_marketable_securities"))
    net_debt = bs.get("net_debt", -bs["net_cash"] if "net_cash" in bs else None)
    return {"ticker": tk, "valuation_date": TODAY,
            "calibration": f"{tk}_calibration_v1.0 ({'+'.join(f['scenario_state'].values())})",
            "market": {"price": m["price"], "shares_outstanding": m["shares_outstanding"], "shares_source": m["shares_source"]},
            "balance_sheet": {"net_debt": net_debt, "cash": cash, "source": bs["source"]},
            "base_period": {"revenue_ttm": bp["revenue_ttm"], "current_fcf_margin": bp["current_fcf_margin"], "revenue_source": bp.get("revenue_formula"), "source": bp.get("fcf_margin_formula")},
            "discounting": {"discount_rate": f["discount_rate"]["base"], "stress_rates": [f["discount_rate"]["stress"]["min"], f["discount_rate"]["stress"]["max"]]},
            "terminal": {"fcf_margin_range": {k: f["terminal_fcf_margin"][k] for k in ("min", "base", "max")}, "multiple_range": {k: f["terminal_fcf_multiple"][k] for k in ("min", "base", "max")}},
            "margin_transition": {"type": f["margin_transition"]["type"], "path": f["margin_transition"]["path"]},
            "calculation": f["calculation"], "scenario_state": f["scenario_state"]}


for tk in TKS:
    print(f"===== {tk} =====")
    cal = yaml.safe_load((PK / f"{tk}_mc_calibration_v1.0.yaml").read_text(encoding="utf-8"))
    eq0 = yaml.safe_load((PK / f"{tk}_calibration_v1.0.yaml").read_text(encoding="utf-8"))["calibration_v1.0"]["market"]["equity_value"]
    if not MC:
        r = post({"model": "reverse_valuation", "inputs": rv_inputs(tk), "seed": 0, "save": True})
        o = r.get("outputs", {}); c = o.get("calculated", {}); ms = o.get("model_stability") or {}
        print(f"RV run {r.get('run_id')}: implied CAGR 5Y {c.get('implied_revenue_cagr_5y')}, TV share {c.get('terminal_value_share_of_pv')}, equity {c.get('equity_value')}, class {ms.get('class')} | preflight IMMA: CAGR {cal['reverse_valuation_ref'].get('implied_revenue_cagr_5y')}")
        if r.get("error"):
            print("RV ERROR:", r["error"])
        v = post({"model": "artifact_validator", "inputs": {"mode": "calibration", "workspace": "/data/workspace-invest", "calibration": cal, "folders": [FOLDER[tk]], "equity_value_0": eq0, "dispersion_paths": 20000}, "seed": 0, "save": True})
        vo = v.get("outputs", v)
        print(f"validator run {v.get('run_id')}: pass {vo.get('pass')} | schema_errors {len(vo.get('schema_errors') or [])} {[(e['path'], e['message'][:80]) for e in (vo.get('schema_errors') or [])[:5]]}")
        for f_ in vo.get("integrity") or []:
            if f_["severity"] != "info":
                print("  ", f_["severity"], f_["rule"], f_["path"], "|", f_["message"][:160])
        for p, a in (vo.get("aggregate_shift") or {}).items():
            print(f"   σ {a['sigma']:.3f} / cap {a['cap']} [{a['kind']}] q{a['quarter']} drivers {a['drivers']} Σ|e| {a['sum_abs_effect']} {'OK' if a['ok'] else 'BREACH'} — {p}")
        d = vo.get("dispersion") or {}
        if d:
            print(f"   дисперсия intrinsic W {d['intrinsic']['W']} / full W {d['full']['W']} (ratio {d.get('full_to_intrinsic_ratio')}) | bands {d.get('bands')}")
        e = vo.get("engine_dry_run") or {}
        print(f"   сухой прогон: mapping_warnings {e.get('mapping_warnings')}, deterministic {e.get('deterministic')}")
    else:
        spec = yaml.safe_load((WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.0.yaml").read_text(encoding="utf-8")) if (WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.0.yaml").exists() else None
        inp = {"calibration": cal, "equity_value_0": eq0, "convergence_check": True, "robustness": True, "robustness_paths": 100000, "store_paths": True}
        if spec is not None:
            inp["joint_layer_spec"] = spec
        r = post({"model": "company_mc", "inputs": inp, "seed": 20260920, "save": True})
        o = r.get("outputs", {}); b = o.get("base", {}); q = (b.get("return") or {}).get("CAGR_5Y_quantiles", {}); rb = o.get("robustness") or {}
        print(f"== {tk} НОРМАТИВ run {r.get('run_id')}: CAGR 3/5/8 {b.get('return', {}).get('median_CAGR_3Y')}/{b.get('return', {}).get('median_CAGR_5Y')}/{b.get('return', {}).get('median_CAGR_8Y')} | q5..q95 {q.get('0.05')}..{q.get('0.95')} | P(loss>30) {b.get('downside', {}).get('P_loss_gt_30pct_5Y')} P(loss>50) {b.get('downside', {}).get('P_loss_gt_50pct_5Y')} | P(2x) {b.get('return', {}).get('P_2x_5Y')} | ES5 {b.get('downside', {}).get('expected_shortfall_5pct_5Y')} | medE5 {b.get('median_equity_value_5Y_b')} | gap RV {b.get('gap_metrics', {}).get('RV_Growth_Gap')} price {b.get('gap_metrics', {}).get('Price_Expectation_Gap')} | conv {(o.get('convergence') or {}).get('stable')} | warnings {(o.get('joint_simulation') or {}).get('mapping_warnings')}")
        print(f"   robustness: pass {rb.get('pass')} (знак {rb.get('same_sign_share')}, допуск {rb.get('within_delta_tolerance_share')}) | runs {[(x['perturbation'], x['value'], round(x['dP_2x_5Y'], 3), round(x['dP_loss_gt_30pct_5Y'], 3)) for x in rb.get('runs', [])]}")
        if o.get("milestones"):
            print("   milestones:", json.dumps(o["milestones"], ensure_ascii=False)[:600])
        if r.get("error"):
            print("MC ERROR:", r["error"])
