"""Ревалидация 9 неизменённых калибровок под Joint v1.1 (MC-G5-013 по измеренной σ зависит от корней/корреляций)."""
import json,urllib.request,yaml
WS="C:/openclaw-lab/data/workspace-invest"; URL="http://127.0.0.1:18791/run"
CAL={"SPCX":("spacex","mc_calibration_v1.1.2.yaml"),"HOOD":("hood","mc_calibration_v1.0.1.yaml"),"RKLB":("rklb","mc_calibration_v1.0.1.yaml"),"LLY":("lly","mc_calibration_v1.0.yaml"),"PLTR":("pltr","mc_calibration_v1.0.yaml"),"NET":("net","mc_calibration_v1.0.yaml"),"ETN":("etn","mc_calibration_v1.0.1.yaml"),"CRWV":("crwv","mc_calibration_v1.0.1.yaml"),"ASTS":("asts","mc_calibration_v1.0.yaml")}
NORM={"SPCX":"20260924T073336Z-company_mc-e55d7d","HOOD":"20260924T074150Z-company_mc-038894","RKLB":"20260924T074358Z-company_mc-224958","LLY":"20260924T074630Z-company_mc-89318c","PLTR":"20260924T180209Z-company_mc-460fe8","NET":"20260924T180403Z-company_mc-a8783a","ETN":"20260924T183027Z-company_mc-c0c4ef","CRWV":"20260925T115341Z-company_mc-a1b31f","ASTS":"20260925T082018Z-company_mc-17e2e2"}
res={}
for tk,(fd,fn) in CAL.items():
    cal=yaml.safe_load(open(f"{WS}/portfolio/{fd}/{fn}",encoding="utf-8")); eq0=json.load(open(f"{WS}/portfolio/_runs/{NORM[tk]}.json",encoding="utf-8"))["inputs"]["equity_value_0"]
    req=urllib.request.Request(URL,data=json.dumps({"model":"artifact_validator","inputs":{"mode":"calibration","workspace":"/data/workspace-invest","calibration":cal,"folders":[fd],"equity_value_0":eq0,"dispersion_paths":20000,"joint_layer_spec_path":"/data/workspace-invest/methodology/Joint_Simulation_Layer_Schema_v1.1.yaml"},"seed":0,"save":True}).encode(),headers={"Content-Type":"application/json"})
    r=json.load(urllib.request.urlopen(req,timeout=1800)); o=r.get("outputs",r)
    agg=o.get("aggregate_shift") or {}; worst=max(((a["sigma"]/a["cap"],p,a["sigma"],a["cap"]) for p,a in agg.items()),default=None)
    bad=[p for p,a in agg.items() if not a["ok"]]
    print(f"{tk}: {r['run_id'][-6:]} pass {o.get('pass')} | breach {bad} | max sigma/cap {worst[0]:.2f} ({worst[1].split('.')[-1]} {worst[2]:.3f}/{worst[3]})" if worst else f"{tk}: {r['run_id'][-6:]} pass {o.get('pass')} | нет целей", flush=True)
    res[tk]={"run_id":r["run_id"],"pass":o.get("pass"),"breach":bad}
json.dump(res,open("C:/Users/alexe/AppData/Local/Temp/claude/C--Users-alexe-PycharmProjects-requirements-analyzer-v3/9e56a7f4-79be-4514-b34b-d15c9a274661/scratchpad/invest/_revalidate_joint11.json","w",encoding="utf-8"),indent=1)
