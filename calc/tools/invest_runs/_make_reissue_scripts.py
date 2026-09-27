"""Собирает _integrate_reissues.py (из _integrate_crwv101.py) и _scenario_normative2.py (из _scenario_normative.py)."""
import ast
import pathlib

S = pathlib.Path(__file__).parent

# ---------- интеграция пяти переизданий ----------
s = (S / "_integrate_crwv101.py").read_text(encoding="utf-8")
reps = [
    ('"""Интеграция принятого переиздания CRWV mc v1.0.1 (пакет IMMA_CRWV_mc_v1.0.1) и RV v1.0 (партия 5) в portfolio/crwv (роль интегратора).',
     '"""Интеграция пяти переизданий под Joint v1.1 (пакет IMMA_Joint_v1.1_Taxonomy_v1.2.1_Company_Reissues): NBIS/NVDA v1.0.3, MSFT v1.0.1,\nMETA v1.0.2, ASML v1.0.2 — файлы в portfolio/<tk>, старая версия mc-файла удаляется из папки (остаётся в from_imma и git), calc_runs +\ninfo_log (в т.ч. патч экспозиций). RV не менялась. Запуск: python _integrate_reissues.py <workspace> NBIS=<run> NVDA=<run> MSFT=<run> META=<run> ASML=<run> [--apply]'),
    ('WS = Path(sys.argv[1]); RUNS = {"CRWV": sys.argv[2]}; APPLY = "--apply" in sys.argv\nONLY = set(os.environ.get("ONLY", "CRWV").split(","))\nRV_RUNS = {"CRWV": "20260925T081450Z-reverse_valuation-55e6d2"}',
     'WS = Path(sys.argv[1]); RUNS = dict(a.split("=", 1) for a in sys.argv[2:] if "=" in a); APPLY = "--apply" in sys.argv\n'
     'ONLY = set(RUNS)\nRV_RUNS = {}\n'
     'NEWFILE = {"NBIS": "NBIS_mc_calibration_v1.0.3.yaml", "NVDA": "NVDA_mc_calibration_v1.0.3.yaml", "MSFT": "MSFT_mc_calibration_v1.0.1.yaml", "META": "META_mc_calibration_v1.0.2.yaml", "ASML": "ASML_mc_calibration_v1.0.2.yaml"}\n'
     'OLDFILE = {"NBIS": "mc_calibration_v1.0.2.yaml", "NVDA": "mc_calibration_v1.0.2.yaml", "MSFT": "mc_calibration_v1.0.yaml", "META": "mc_calibration_v1.0.1.yaml", "ASML": "mc_calibration_v1.0.1.yaml"}\n'
     'VALRUN = {"NBIS": "dc309a", "NVDA": "cab5d4", "MSFT": "87cf9f", "META": "a5afb8", "ASML": "e551d8"}\n'
     'DELTA = {"NBIS": "миграция схемы 1.0.1→1.0.2 (parity-gated смесь; migration delta ожидаема) + ACCELERATOR_PRICE_COMPETITION (+1)", '
     '"NVDA": "миграция схемы 1.0.1→1.0.2 (parity-gated смесь; migration delta ожидаема) + ACCELERATOR_PRICE_COMPETITION (−2)", '
     '"MSFT": "ACCELERATOR_PRICE_COMPETITION (+1) + знаки TAIWAN_SUPPLY исправлены (−1→+1, канон «здоровье поставок»)", '
     '"META": "ACCELERATOR_PRICE_COMPETITION (+1) + знаки TAIWAN_SUPPLY исправлены (−1→+1)", "ASML": "ACCELERATOR_PRICE_COMPETITION (−1)"}'),
    ('SRC1 = WS / "from_imma" / "CRWV_ASTS_SPOT_Calibrations_v1"\nSRC2 = WS / "from_imma" / "CRWV_mc_v1.0.1"   # переиздание mc v1.0.1',
     'SRC2 = WS / "from_imma" / "Joint_v1.1_Taxonomy_v1.2.1_Reissues"'),
    ('def _mc(tk):\n    return (SRC2 / f"{tk}_mc_calibration_v1.0.1.yaml", "mc_calibration_v1.0.1.yaml") if (SRC2 / f"{tk}_mc_calibration_v1.0.1.yaml").exists() else (SRC1 / f"{tk}_mc_calibration_v1.0.yaml", "mc_calibration_v1.0.yaml")\n'
     'PLAN = {tk: (tk.lower(), [(SRC1 / f"{tk}_calibration_v1.0.yaml", "calibration_v1.0.yaml"), _mc(tk)]) for tk in ("CRWV",) if tk in ONLY}\nNOW = "2026-09-25T12:30:00Z"',
     'PLAN = {tk: (tk.lower(), [(SRC2 / NEWFILE[tk], NEWFILE[tk].split("_", 1)[1])]) for tk in NEWFILE if tk in ONLY}\nNOW = "2026-09-25T14:00:00Z"'),
    ('"purpose": "нормативный прогон принятого переиздания CRWV mc v1.0.1 (архетип B; v1.0 отклонена по MC-G5-013: σ capex_revenue_nodes.Y2 0.056 > 0.05; в v1.0.1 три вклада ×0.85 → измеренная σ 0.048; валидатор 1.7.0 …-d97b71 pass, check_supersedes: пропаж 0 / изменено 3; intrinsic W 0.605 / full 0.647 — ориентир B; сходимость stable, robustness 1.0/0.875)"',
     '"purpose": f"нормативный прогон переиздания {tk} {cal_name} под Joint_Simulation_Layer_Schema v1.1 (пакет IMMA 25.09: {DELTA[tk]}; check_supersedes к предыдущей версии — пропаж 0; валидатор 1.7.0 …-{VALRUN[tk]} pass, MC-G5-013 по измеренной σ под Joint v1.1; экспозиции mpc_inputs по Scenario_Company_Exposure_Patch_v1.1, таксономия 1.2.1)"'),
    ('"summary": f"Интеграция калибровки CRWV: RV v1.0 (партия 5) и переиздание mc v1.0.1 (25.09, MC-G5-013 снят: σ 0.048 ≤ 0.05): {\', \'.join(n for _, n in files)} приняты (валидатор 1.7.0 режим calibration pass, check_supersedes OK); нормативные прогоны: "',
     '"summary": f"Переиздание {tk} {files[-1][1]} под Joint v1.1 (пакет IMMA 25.09; {DELTA[tk]}): принято (check_supersedes OK, валидатор 1.7.0 …-{VALRUN[tk]} pass); прежний файл {OLDFILE[tk]} удалён из папки (from_imma/git); mpc_inputs: Scenario_Company_Exposure_Patch_v1.1 применён, driver_taxonomy_version 1.2.1; прежние прогоны остаются записями воспроизводимости; новый нормативный прогон: "'),
    ('    sp = fd / "state.json"; raw = open(sp, encoding="utf-8", newline="").read(); st = json.loads(raw)',
     '    old = fd / OLDFILE[tk]\n    if old.exists():\n        changes.append(f"{folder}/{OLDFILE[tk]}: удалить (прежняя версия; копия в from_imma и git)")\n        if APPLY: old.unlink()\n'
     '    sp = fd / "state.json"; raw = open(sp, encoding="utf-8", newline="").read(); st = json.loads(raw)'),
]
for a, b in reps:
    assert s.count(a) == 1, a[:80]
    s = s.replace(a, b)
i = s.index("# _candidates.yaml"); j = s.index("for c in changes")
s = s[:i] + s[j:]
ast.parse(s)
(S / "_integrate_reissues.py").write_text(s, encoding="utf-8"); print("integrate ok")

# ---------- нормативный сценарный раунд 2 ----------
t = (S / "_scenario_normative.py").read_text(encoding="utf-8")
reps2 = [
    ('"""Нормативные сценарные прогоны Scenario Engine v1.0 (25.09): 13 компаний',
     '"""Нормативный сценарный раунд 2 под Joint v1.1 (25.09): 14 компаний (переиздания NBIS/NVDA v1.0.3, MSFT v1.0.1, META v1.0.2, ASML v1.0.2; RKLB BASE перепрогнан под v1.1; ETN v1.0.1 — с флагом MC-G5-013 под v1.1 до переиздания)'),
    ('"NBIS": ("nbis", "mc_calibration_v1.0.2.yaml"), "NVDA": ("nvda", "mc_calibration_v1.0.2.yaml")', '"NBIS": ("nbis", "mc_calibration_v1.0.3.yaml"), "NVDA": ("nvda", "mc_calibration_v1.0.3.yaml")'),
    ('"META": ("meta", "mc_calibration_v1.0.1.yaml"), "ASML": ("asml", "mc_calibration_v1.0.1.yaml")', '"META": ("meta", "mc_calibration_v1.0.2.yaml"), "ASML": ("asml", "mc_calibration_v1.0.2.yaml")'),
    ('"MSFT": ("msft", "mc_calibration_v1.0.yaml"), "PLTR"', '"MSFT": ("msft", "mc_calibration_v1.0.1.yaml"), "PLTR"'),
    ('"ASTS": ("asts", "mc_calibration_v1.0.yaml")}', '"ASTS": ("asts", "mc_calibration_v1.0.yaml"), "CRWV": ("crwv", "mc_calibration_v1.0.1.yaml")}'),
    ('"ASTS": "20260925T082018Z-company_mc-17e2e2"}',
     '"ASTS": "20260925T082018Z-company_mc-17e2e2", "CRWV": "20260925T115341Z-company_mc-a1b31f"}\nNORM.update(json.load(open(S / "_norm_runs_joint11.json", encoding="utf-8")))   # NBIS/NVDA/MSFT/META/ASML/RKLB под Joint v1.1'),
    ('spec = yaml.safe_load((WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.0.yaml").read_text(encoding="utf-8"))',
     'spec = yaml.safe_load((WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.1.yaml").read_text(encoding="utf-8"))'),
    ('res_path = S / "_scenario_normative.json"', 'res_path = S / "_scenario_normative2.json"'),
    ('for label, w, dp in (("current", {tk: wcur[tk] for tk in CAL}, cash_w), ("optimum_run4", w_opt, dp_opt)):',
     'for label, w, dp in (("current", {tk: wcur[tk] for tk in CAL}, cash_w), ("optimum_run4", w_opt, dp_opt)):\n        w = {tk: x for tk, x in w.items() if tk in CAL}'),
]
for a, b in reps2:
    assert t.count(a) == 1, a[:80]
    t = t.replace(a, b)
ast.parse(t)
(S / "_scenario_normative2.py").write_text(t, encoding="utf-8"); print("scenario2 ok")
