"""Интеграция партии 18 (закрытие 17 пробелов MC-G5-014): (1) mc-калибровки ETN v1.0.3 / MSFT v1.0.2 / NET v1.0.1 / PLTR v1.0.1 — копия
(check_supersedes: пропаж 0, изменён только as_of + добавлены mapping); (2) mpc_inputs — ТОЛЬКО ДЕЛЬТА в хостовые файлы (шесть файлов IMMA
реконструированы и расходятся с хостом: таксономия, экспозиции UTILITY_CAPEX / ELECTRIFICATION_GRID / DIGITAL_AD_DEMAND / TAIWAN_SUPPLY у
CRWV и MSFT, пропавшие failure mode / benchmark у SPOT, taxonomy_gap у ETN) — дописываются объекты driver_interpretation.<drv>.
scenario_mapping_exception, версия и запись changelog; HPS.A — замена целиком (supersedes точный). Хостовый формат (CRLF, комментарий
первой строки) сохраняется: правка текстом через ruamel недоступна → YAML перечитывается и дописывается блоком в конец документа.
Сухой прогон по умолчанию; --apply — запись. Запуск: python _integrate_party18.py [--apply]"""
import re
import shutil
import sys
from pathlib import Path

import yaml

WS = Path("C:/openclaw-lab/data/workspace-invest"); PK = WS / "from_imma" / "Party18_MC_G5_014_Closures_v1.0"; APPLY = "--apply" in sys.argv
MPC = {"crwv": "CRWV_mpc_inputs_v1.0.2", "etn": "ETN_mpc_inputs_v1.0.3", "msft": "MSFT_mpc_inputs_v1.0.2", "net": "NET_mpc_inputs_v1.0.1", "pltr": "PLTR_mpc_inputs_v1.0.1", "spot": "SPOT_mpc_inputs_v1.0.1"}
MC = {"etn": "ETN_mc_calibration_v1.0.3", "msft": "MSFT_mc_calibration_v1.0.2", "net": "NET_mc_calibration_v1.0.1", "pltr": "PLTR_mc_calibration_v1.0.1"}
plan = []
# 1) mc-калибровки — копия
for fd, name in MC.items():
    dst = WS / "portfolio" / fd / (name.split("_", 1)[1] + ".yaml")
    plan.append(f"copy {name}.yaml → portfolio/{fd}/{dst.name}")
    if APPLY:
        shutil.copyfile(PK / f"{name}.yaml", dst)
# 2) HPS.A — замена целиком
plan.append("copy HPSA_mpc_inputs_v1.0.2.yaml → portfolio/hps_a/mpc_inputs.yaml (supersedes точный)")
if APPLY:
    shutil.copyfile(PK / "HPSA_mpc_inputs_v1.0.2.yaml", WS / "portfolio/hps_a/mpc_inputs.yaml")
# 3) шесть файлов — дельта
for fd, name in MPC.items():
    hp = WS / "portfolio" / fd / "mpc_inputs.yaml"; raw = hp.read_bytes().decode("utf-8"); crlf = "\r\n" in raw; txt = raw.replace("\r\n", "\n")
    host = yaml.safe_load(txt); new = yaml.safe_load((PK / f"{name}.yaml").read_text(encoding="utf-8"))
    exc = {d: {"scenario_mapping_exception": v["scenario_mapping_exception"]} for d, v in (new.get("driver_interpretation") or {}).items() if isinstance(v, dict) and v.get("scenario_mapping_exception")}
    if not exc:
        plan.append(f"{fd}: исключений нет — пропуск"); continue
    hv = host.get("driver_exposure_vector") or {}
    for d in exc:
        assert hv.get(d) not in (0, None), f"{fd}: экспозиция {d} на хосте = {hv.get(d)} — исключение не нужно"
    ver_new = str(new.get("version")); ver_old = str(host.get("version"))
    interp = host.get("driver_interpretation") or {}
    for d, v in exc.items():
        interp.setdefault(d, {}); interp[d]["scenario_mapping_exception"] = v["scenario_mapping_exception"]
    # текстовая правка: version, changelog (добавить запись), driver_interpretation (заменить блок или дописать в конец)
    t = re.sub(r"^version: .*$", f"version: '{ver_new}'", txt, count=1, flags=re.M)
    entry = yaml.safe_dump([{"date": "2026-10-04", "change": f"Party 18 (IMMA review IMMA-P18-MCG5-014-20261004): структурные исключения MC-G5-014 для {', '.join(sorted(exc))}; экспозиции и failure modes не менялись; интегратор внёс только дельту (файл IMMA {name} реконструирован и расходится с хостом)"}], allow_unicode=True, sort_keys=False, width=1000)
    if re.search(r"^changelog:\s*$", t, flags=re.M):
        t = re.sub(r"^(changelog:\s*\n)", lambda m: m.group(1) + entry, t, count=1, flags=re.M)
    else:
        t = t.rstrip("\n") + "\nchangelog:\n" + entry
    t = re.sub(r"^driver_interpretation:\n(?:[ \t]+.*\n?)*", "", t, flags=re.M)                       # старый блок (если был) — заменяем
    t = t.rstrip("\n") + "\n" + yaml.safe_dump({"driver_interpretation": interp}, allow_unicode=True, sort_keys=False, width=1000)
    chk = yaml.safe_load(t)
    assert chk["driver_exposure_vector"] == hv and chk.get("failure_modes") == host.get("failure_modes") and chk.get("benchmark") == host.get("benchmark"), f"{fd}: инвариант нарушен"
    assert all(chk["driver_interpretation"][d]["scenario_mapping_exception"] == exc[d]["scenario_mapping_exception"] for d in exc)
    plan.append(f"{fd}: version {ver_old} → {ver_new}; +исключения {sorted(exc)}; changelog +1")
    if APPLY:
        hp.write_bytes((t.replace("\n", "\r\n") if crlf else t).encode("utf-8"))
for p in plan:
    print("-", p)
print("режим:", "ЗАПИСЬ" if APPLY else "сухой прогон")
