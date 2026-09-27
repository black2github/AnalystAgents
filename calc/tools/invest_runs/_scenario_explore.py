"""РАЗВЕДОЧНЫЙ прогон сценариев (24.09, решение владельца): НЕ норматив, НЕ оценка — ориентир масштаба для заказа
сценарного слоя у IMMA. Движок company_mc 2.3.2 принимает scenario.driver_overrides {mean_shift_sigma, volatility_multiplier}
(постоянный сдвиг стандартизированного шока драйвера на всём горизонте; effective_from / затухание сценария движок не
поддерживает — ограничение разведки). Величины сдвигов — model_assumption интегратора, помечены как черновые.
Сценарий CHIP_COLD_WAR — по уточнению владельца (превосходство Китая + гонка США), не «паритет». Для каждого сценария: 12 компаний × 100k совместных путей (общий global_seed 20260920) → portfolio_paths на текущих весах
(94.5 % NAV перенормированы) и на весах оптимума захода 4 (…-d58516). Сравнение с BASE на тех же 100k путях."""
import json
import sys
import time
import urllib.request
from pathlib import Path

import yaml

S = Path(__file__).parent; WS = Path("C:/openclaw-lab/data/workspace-invest"); URL = "http://127.0.0.1:18791/run"
CAL = {"SPCX": ("spacex", "mc_calibration_v1.1.2.yaml"), "NBIS": ("nbis", "mc_calibration_v1.0.2.yaml"), "NVDA": ("nvda", "mc_calibration_v1.0.2.yaml"), "HOOD": ("hood", "mc_calibration_v1.0.1.yaml"),
       "RKLB": ("rklb", "mc_calibration_v1.0.1.yaml"), "LLY": ("lly", "mc_calibration_v1.0.yaml"), "META": ("meta", "mc_calibration_v1.0.1.yaml"), "ASML": ("asml", "mc_calibration_v1.0.1.yaml"),
       "MSFT": ("msft", "mc_calibration_v1.0.yaml"), "PLTR": ("pltr", "mc_calibration_v1.0.yaml"), "NET": ("net", "mc_calibration_v1.0.yaml"), "ETN": ("etn", "mc_calibration_v1.0.1.yaml")}
PATHS = 100000
NORM = {"SPCX": "20260924T073336Z-company_mc-e55d7d", "NBIS": "20260924T073647Z-company_mc-0daf30", "NVDA": "20260924T073919Z-company_mc-d5afc5", "HOOD": "20260924T074150Z-company_mc-038894",
        "RKLB": "20260924T074358Z-company_mc-224958", "LLY": "20260924T074630Z-company_mc-89318c", "META": "20260924T074844Z-company_mc-965cab", "ASML": "20260924T075104Z-company_mc-aa8132",
        "MSFT": "20260924T175814Z-company_mc-a26670", "PLTR": "20260924T180209Z-company_mc-460fe8", "NET": "20260924T180403Z-company_mc-a8783a", "ETN": "20260924T183027Z-company_mc-c0c4ef"}
# Черновые сценарии (сдвиг в σ драйвера, постоянный на горизонте; знак: положительное значение драйвера благоприятно компаниям с экспозицией +)
SCENARIOS = {
    "BASE": {},
    "CHIP_COLD_WAR": {  # уточнение владельца 24.09: технологическое превосходство Китая + гонка США с государственными деньгами («холодная война» в чипах);
                        # разведка даёт только установившийся уровень гонки — переходная фаза у границы паритета требует сценария с фазами (effective_from, ramp), движок этого не умеет
        "SEMICONDUCTOR_WFE": {"mean_shift_sigma": 1.5, "volatility_multiplier": 1.3},   # западная стройка фабов на госденьги: спрос на оборудование
        "INDUSTRIAL_RESHORING": {"mean_shift_sigma": 1.5},                                 # решоринг производства
        "GOVERNMENT_DEFENSE": {"mean_shift_sigma": 1.5},                                   # госзаказ: чипы, ПО и LLM для военных нужд
        "HYPERSCALER_CAPEX": {"mean_shift_sigma": 1.0, "volatility_multiplier": 1.3},     # гонка мощностей продолжается на госстимулах
        "DATA_CENTER_POWER": {"mean_shift_sigma": 0.5},                                    # энергия — узкое место гонки
        "CHINA_REVENUE": {"mean_shift_sigma": -2.0, "volatility_multiplier": 1.3},        # разрыв рынков: две производственные системы
        "TAIWAN_SUPPLY": {"mean_shift_sigma": -1.0, "volatility_multiplier": 1.3},        # роль тайваньской цепочки снижается
        "AI_CLOUD_PRICING": {"mean_shift_sigma": -1.0},                                   # дешёвые китайские чипы вне Запада давят цену вычислений
        "INTEREST_RATES": {"mean_shift_sigma": 0.5},                                       # госрасходы и дефициты → ставки выше
    },
    "TAIWAN_SEIZURE": {  # силовой: черновик по примеру Joint Spec §6.1 (ненормативный), постоянный сдвиг — грубее реального шока с восстановлением
        "TAIWAN_SUPPLY": {"mean_shift_sigma": -2.0, "volatility_multiplier": 1.5},
        "CHINA_REVENUE": {"mean_shift_sigma": -2.0, "volatility_multiplier": 1.5},
        "AI_COMPUTE_DEMAND": {"mean_shift_sigma": -1.0},
        "HBM_MEMORY": {"mean_shift_sigma": -1.0}, "ADVANCED_PACKAGING": {"mean_shift_sigma": -1.0}, "SEMICONDUCTOR_WFE": {"mean_shift_sigma": -1.0},
        "CAPITAL_MARKETS": {"mean_shift_sigma": -1.0},
        "GOVERNMENT_DEFENSE": {"mean_shift_sigma": 1.0},
    },
}
ONLY = [a for a in sys.argv[1:] if a in SCENARIOS] or list(SCENARIOS)


def post(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        return json.load(r)


spec = yaml.safe_load((WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.0.yaml").read_text(encoding="utf-8"))
p = yaml.safe_load((WS / "portfolio/_portfolio.yaml").read_text(encoding="utf-8")); wcur = p["machine_outputs"]["current_weights"]; cash_w = round(1.0 - sum(wcur.values()), 4)
opt = json.load(open(WS / "portfolio/_runs/20260924T183808Z-portfolio_optimizer-d58516.json", encoding="utf-8"))["outputs"]
w_opt = {t: w for t, w in opt["proposed_weights"].items() if w > 0}; dp_opt = opt["dry_powder_weight"]
res_path = S / "_scenario_explore.json"; RES = json.load(open(res_path, encoding="utf-8")) if res_path.exists() else {}
for sc in ONLY:
    ov = SCENARIOS[sc]; RES.setdefault(sc, {"companies": {}, "portfolio": {}})
    print(f"===== {sc} =====", flush=True)
    for tk, (folder, fname) in CAL.items():
        if tk in RES[sc]["companies"]:
            continue
        cal = yaml.safe_load((WS / "portfolio" / folder / fname).read_text(encoding="utf-8"))
        eq0 = json.load(open(WS / "portfolio/_runs" / f"{NORM[tk]}.json", encoding="utf-8"))["inputs"]["equity_value_0"]   # стартовая стоимость — из нормативного прогона (у SPCX старый формат RV)
        active = set((cal.get("joint_simulation") or {}).get("active_drivers") or [])
        inp = {"calibration": cal, "equity_value_0": eq0, "joint_layer_spec": spec, "paths": PATHS, "convergence_check": False, "robustness": False, "store_paths": True}
        if ov:
            inp["scenario"] = {"id": sc, "driver_overrides": {d: v for d, v in ov.items() if d in active}}
        t0 = time.time(); r = post({"model": "company_mc", "inputs": inp, "seed": 20260920, "save": True}); o = r["outputs"]; b = o["base"]; q = b["return"]["CAGR_5Y_quantiles"]
        rec = {"run_id": r["run_id"], "applied_drivers": sorted(d for d in ov if d in active), "median_CAGR_5Y": b["return"]["median_CAGR_5Y"], "q05": q["0.05"], "q95": q["0.95"],
               "P_loss_gt_30pct_5Y": b["downside"]["P_loss_gt_30pct_5Y"], "ES5": b["downside"]["expected_shortfall_5pct_5Y"], "P_2x_5Y": b["return"]["P_2x_5Y"], "paths_file": o.get("paths_file")}
        RES[sc]["companies"][tk] = rec; json.dump(RES, open(res_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  {tk}: {r['run_id'][-6:]} {time.time() - t0:.0f}s | median {rec['median_CAGR_5Y']:+.3f} q5..q95 {rec['q05']:+.3f}..{rec['q95']:+.3f} P(l30) {rec['P_loss_gt_30pct_5Y']:.3f} ES5 {rec['ES5']:+.3f} | drivers {rec['applied_drivers']}", flush=True)
    files = {tk: RES[sc]["companies"][tk]["paths_file"] for tk in CAL}
    for label, w, dp in (("current", {tk: wcur[tk] for tk in CAL}, cash_w), ("optimum_run4", w_opt, dp_opt)):
        s = sum(w.values()) + dp
        r = post({"model": "portfolio_paths", "inputs": {"paths_files": files, "weights": {tk: x / s for tk, x in w.items()}, "dry_powder_weight": dp / s, "dry_powder_return_annual": 0.04}, "seed": 0, "save": True})
        o = r["outputs"]; y5 = o["horizons"]["Y5"]
        RES[sc]["portfolio"][label] = {"run_id": r["run_id"], "median_CAGR_5Y": y5["median_CAGR"], "P_loss_gt_30pct": y5["P_loss_gt_30pct"], "P_loss_gt_50pct": y5["P_loss_gt_50pct"], "ES5": y5["expected_shortfall_5pct"], "P_2x": y5["P_2x"], "q05": y5["CAGR_quantiles"]["0.05"], "q95": y5["CAGR_quantiles"]["0.95"], "contribution": o["median_contribution_Y5"]}
        print(f"  портфель [{label}] {r['run_id'][-6:]}: median {y5['median_CAGR']:+.3f} q5..q95 {y5['CAGR_quantiles']['0.05']:+.3f}..{y5['CAGR_quantiles']['0.95']:+.3f} P(l30) {y5['P_loss_gt_30pct']:.3f} ES5 {y5['expected_shortfall_5pct']:+.3f} P(2x) {y5['P_2x']:.3f}", flush=True)
    json.dump(RES, open(res_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
# сводная таблица Δ к BASE
if "BASE" in RES and len(RES) > 1:
    print("\n===== Δ к BASE (медиана CAGR 5Y, п.п. | P(loss>30), п.п.) =====")
    for sc in RES:
        if sc == "BASE": continue
        row = []
        for tk in CAL:
            b = RES["BASE"]["companies"].get(tk); s = RES[sc]["companies"].get(tk)
            if b and s: row.append(f"{tk} {100 * (s['median_CAGR_5Y'] - b['median_CAGR_5Y']):+.1f}/{100 * (s['P_loss_gt_30pct_5Y'] - b['P_loss_gt_30pct_5Y']):+.1f}")
        print(sc + ": " + " | ".join(row))
        for label in ("current", "optimum_run4"):
            b = RES["BASE"]["portfolio"].get(label); s = RES[sc]["portfolio"].get(label)
            if b and s: print(f"   портфель [{label}]: медиана {100 * b['median_CAGR_5Y']:.1f} → {100 * s['median_CAGR_5Y']:.1f} % | P(l30) {100 * b['P_loss_gt_30pct']:.1f} → {100 * s['P_loss_gt_30pct']:.1f} % | ES5 {100 * b['ES5']:+.1f} → {100 * s['ES5']:+.1f} %")
