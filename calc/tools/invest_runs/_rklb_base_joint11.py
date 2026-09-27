"""RKLB v1.0.1: нормативный BASE 500k под Joint v1.1 (INDUSTRIAL_RESHORING получил корни → пути меняются), robustness."""
import json,urllib.request,yaml
WS="C:/openclaw-lab/data/workspace-invest"; URL="http://127.0.0.1:18791/run"
cal=yaml.safe_load(open(f"{WS}/portfolio/rklb/mc_calibration_v1.0.1.yaml",encoding="utf-8")); eq0=json.load(open(f"{WS}/portfolio/_runs/20260924T074358Z-company_mc-224958.json",encoding="utf-8"))["inputs"]["equity_value_0"]
spec=yaml.safe_load(open(f"{WS}/methodology/Joint_Simulation_Layer_Schema_v1.1.yaml",encoding="utf-8"))
req=urllib.request.Request(URL,data=json.dumps({"model":"company_mc","inputs":{"calibration":cal,"equity_value_0":eq0,"joint_layer_spec":spec,"convergence_check":True,"robustness":True,"robustness_paths":100000,"store_paths":True},"seed":20260920,"save":True}).encode(),headers={"Content-Type":"application/json"})
r=json.load(urllib.request.urlopen(req,timeout=12*3600)); o=r["outputs"]; b=o["base"]; q=b["return"]["CAGR_5Y_quantiles"]; rb=o.get("robustness") or {}
print(f"RKLB под v1.1: {r['run_id']} | CAGR 3/5/8 {b['return']['median_CAGR_3Y']:.4f}/{b['return']['median_CAGR_5Y']:.4f}/{b['return']['median_CAGR_8Y']:.4f} | q5..q95 {q['0.05']:.3f}..{q['0.95']:.3f} | P(l30) {b['downside']['P_loss_gt_30pct_5Y']:.4f} P(l50) {b['downside']['P_loss_gt_50pct_5Y']:.4f} | P(2x) {b['return']['P_2x_5Y']:.4f} | ES5 {b['downside']['expected_shortfall_5pct_5Y']:.4f} | medE5 {b['median_equity_value_5Y_b']:.2f} | conv {(o.get('convergence') or {}).get('stable')} | robustness {rb.get('pass')} {rb.get('same_sign_share')}/{rb.get('within_delta_tolerance_share')}")
print("milestones:",json.dumps(o.get("milestones"),ensure_ascii=False)[:400])
