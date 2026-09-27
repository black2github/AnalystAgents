"""Диагностика ETN v1.0.1 под Joint v1.1: базлайн под v1.0 (валидатор 1.7.0), драйверы на ElectricalAmericas, копии с
равномерным масштабом вкладов на ElectricalAmericas ×0.90 / ×0.85 (канон не трогаем)."""
import copy,json,urllib.request,yaml
WS="C:/openclaw-lab/data/workspace-invest"; URL="http://127.0.0.1:18791/run"; T="revenue_model.segments.ElectricalAmericas.initial_growth"
cal=yaml.safe_load(open(f"{WS}/portfolio/etn/mc_calibration_v1.0.1.yaml",encoding="utf-8")); eq0=json.load(open(f"{WS}/portfolio/_runs/20260924T183027Z-company_mc-c0c4ef.json",encoding="utf-8"))["inputs"]["equity_value_0"]
print("драйверы на цели:",[(m["driver_id"],t["effect_per_plus_1sigma"],t.get("lag_quarters"),t.get("decay_half_life_quarters")) for m in cal["driver_parameter_mapping"] for t in m["stochastic_targets"] if t["path"]==T])
def run(c,spec,label):
    req=urllib.request.Request(URL,data=json.dumps({"model":"artifact_validator","inputs":{"mode":"calibration","workspace":"/data/workspace-invest","calibration":c,"folders":["etn"],"equity_value_0":eq0,"dispersion_paths":20000,"joint_layer_spec_path":f"/data/workspace-invest/methodology/Joint_Simulation_Layer_Schema_v{spec}.yaml"},"seed":0,"save":False}).encode(),headers={"Content-Type":"application/json"})
    o=json.load(urllib.request.urlopen(req,timeout=1800)).get("outputs"); a=o["aggregate_shift"][T]; d=o.get("dispersion") or {}
    print(f"{label}: pass {o['pass']} | sigma {a['sigma']:.3f}/{a['cap']} sum|e| {a['sum_abs_effect']} | W {d.get('intrinsic',{}).get('W')}/{d.get('full',{}).get('W')}",flush=True)
run(cal,"1.0","v1.0.1 под Joint v1.0 ")
run(cal,"1.1","v1.0.1 под Joint v1.1 ")
for k in (0.90,0.85):
    c=copy.deepcopy(cal)
    for m in c["driver_parameter_mapping"]:
        for t in m["stochastic_targets"]:
            if t["path"]==T: t["effect_per_plus_1sigma"]=round(t["effect_per_plus_1sigma"]*k,6)
    run(c,"1.1",f"копия x{k} под v1.1     ")
