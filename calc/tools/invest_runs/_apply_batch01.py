"""Партия 1 моделей компаний (NBIS, NVDA, HOOD) от другой LLM → папки portfolio/<тикер>/ в формате дозора;
ответы владельца 21.09 (кэш P2 = 0, SPCX в P1, XLC/XLV/ARKF приняты, AI_COMPUTE без внешнего benchmark) → _portfolio.yaml;
пересчёт portfolio_regime."""
import json, shutil, urllib.request
from pathlib import Path
import yaml

D = Path("C:/Users/alexe/Downloads")
Q = json.load(open("_quotes_2026-09-20.json", encoding="utf-8"))
TODAY = "2026-09-21"
SHARE = "https://chatgpt.com/share/6ab04f22-52b4-83eb-ab75-17495e90bb0f"
COMPANIES = {
    "NBIS": {"folder": "nbis", "company": "Nebius Group N.V.", "exchange": "NASDAQ", "sector_id": "AI_COMPUTE"},
    "NVDA": {"folder": "nvda", "company": "NVIDIA Corporation", "exchange": "NASDAQ", "sector_id": "SEMICONDUCTORS"},
    "HOOD": {"folder": "hood", "company": "Robinhood Markets, Inc.", "exchange": "NASDAQ", "sector_id": "FINTECH"},
}
AXIS_RU = {  # пояснение осей по-русски (правило языка AGENTS.md)
    "Demand_Monetization": "спрос и монетизация AI-облака", "Unit_Economics": "юнит-экономика AI-облака",
    "Capacity_Secured": "законтрактованная мощность (ГВт)", "Capital_Intensity": "капиталоёмкость (capex к выручке)",
    "Funding_Liquidity": "финансирование и ликвидность", "AI_Demand": "спрос на AI (выручка Data Center)",
    "Gross_Margin": "валовая маржа", "Customer_Breadth": "широта клиентской базы (доля ACIE)",
    "Supply_Commitment": "обязательства перед поставщиками", "China_Access": "доступ на рынок Китая",
    "Customer_Asset_Scale": "масштаб клиентов и активов", "Revenue_Diversification": "диверсификация выручки",
    "Profitability": "прибыльность", "Credit_Risk": "кредитный риск", "Regulatory_Product": "регуляторные ограничения продуктов",
}

def dump(obj):
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, width=120)

for tk, c in COMPANIES.items():
    src = D / f"{tk}_company_state_v1.0.yaml"
    d = yaml.safe_load(src.read_text(encoding="utf-8"))
    out = Path("portfolio") / c["folder"]; out.mkdir(parents=True, exist_ok=True)
    Path("inbox/received").mkdir(parents=True, exist_ok=True)
    shutil.copy(src, Path("inbox/received") / src.name)
    sources = d.get("sources", {})
    src_note = f"inbox/received/{src.name} (другая LLM, партия 1, {TODAY}, share {SHARE})"

    # --- states.yaml ---
    axes = {}
    for ax, v in d["states"].items():
        axes[ax] = {"name": ax.replace("_", " "), "name_ru": AXIS_RU.get(ax, ax),
                    "states": {code: {"name": st["name"], "criteria": st["criteria"]} for code, st in v["states"].items()},
                    "current": v["current"], "current_evidence": v.get("current_evidence", []), "source_refs": v.get("source_refs", [])}
    states = {"version": "1.0", "artifact": f"{tk} State Vector", "as_of": TODAY, "ticker": tk, "source_artifact": src_note,
              "purpose": "Оси и состояния компании. Условия переходов — в triggers.yaml (поле transition). Текущий вектор — state.json → scenario_state.",
              "semantics": d.get("semantics", {}), "sources": sources, "axes": axes}
    (out / "states.yaml").write_text(f"# Вектор состояний {tk} (оси и состояния). Переходы — triggers.yaml, текущий вектор — state.json.\n" + dump(states), encoding="utf-8")

    # --- kpis.yaml ---
    kp = []
    for k in d["kpis"]:
        e = {"id": k["id"], "name": k["name"], "unit": k.get("unit"), "period": k.get("period"),
             "source": "SEC" if "sec.gov" in str(k.get("source", "")) else "IR",
             "thresholds": k.get("zones"), "last_value": k.get("current_value", k.get("current_value_range")),
             "last_date": k.get("as_of"), "source_url": k.get("source"),
             "verified": False}   # значения от LLM — до сверки с первоисточником (задание facts-verify) не используются для переходов
        for opt in ("formula", "note"):
            if opt in k: e[opt] = k[opt]
        kp.append(e)
    kpis = {"version": "1.0", "artifact": f"{tk} KPI Dashboard", "as_of": TODAY, "ticker": tk, "max_critical_kpis": 10,
            "source_artifact": src_note, "zone_semantics": d["kpis"] and d.get("zone_semantics") or {"thresholds_provenance": "model_assumption"},
            "source_policy": {"primary": ["SEC", f"{c['company']} Investor Relations"], "secondary": ["Yahoo Finance"],
                              "rule": "Last value без подтверждённого источника (verified: true) не используется для перехода состояния."},
            "critical_kpis": kp}
    (out / "kpis.yaml").write_text(f"# KPI {tk} с порогами Green/Yellow/Red. История — state.json → kpi_observations.\n" + dump(kpis), encoding="utf-8")

    # --- triggers.yaml (формат реестра дозора) ---
    trig = []
    for t in d["triggers"]:
        fr, to = t["transition"]["from"], t["transition"]["to"]
        trig.append({"id": t["id"], "class": "event", "step": "vector", "axis": t["axis"], "transition": {"from": fr, "to": to},
                     "level": t.get("level", "E2"), "kpis": t.get("kpis", []), "condition": t["condition"], "period": t.get("period"),
                     "source": "первичный источник по kpis.yaml (SEC 10-Q/10-K, пресс-релизы IR)",
                     "action": f"Зафиксировать переход {t['axis']} {fr}→{to} в state.json (state_transitions, scenario_state) и отправить Decision Request владельцу; инвестиционное действие не предопределено",
                     "automation": None, "status": "planned", "fired": []})
    hdr = f"""# Реестр триггеров: {c['company']} ({tk})
# Единственный нормативный дом того, ЧТО отслеживаем. Источник: {src_note}.
# Классы: event | price | calendar | digest. Статусы: active | planned | due | done | dropped. Все пороги — model_assumption.
# Тезис владельца по этой бумаге не записан: позиция фактическая (унаследована), см. thesis.md.
"""
    reg = {"meta": {"ticker": tk, "company": c["company"], "exchange": c["exchange"], "yahoo_symbol": tk,
                    "registry_updated": TODAY, "source_artifact": src_note,
                    "price_source": f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?range=1d&interval=1d (поле meta.regularMarketPrice)",
                    "price_at_registry": Q[tk]["price"], "position": "фактическая позиция владельца, см. portfolio/_portfolio.yaml"},
           "automations": {"_note": "дозор событий по этим триггерам ещё не заведён (очередь); вечерняя сводка обходит папку"},
           "route": {"steps": [{"id": "vector", "kind": "axis", "name": "Вектор состояний по осям states.yaml — фазы стратегии владельца не заданы"}]},
           "rules": d["triggers"] and {"evidence_required": True, "pending_verification_blocks_transition": True, "trigger_not_decision": True},
           "triggers": trig}
    (out / "triggers.yaml").write_text(hdr + dump(reg), encoding="utf-8")

    # --- mpc_inputs.yaml ---
    mpc = {"version": "1.0", "ticker": tk, "artifact": "mpc_inputs", "as_of": TODAY, "source_artifact": src_note, **d["mpc_inputs"]}
    (out / "mpc_inputs.yaml").write_text(f"# Входы MPC для {tk}: вектор экспозиций по драйверам и failure modes (Marginal_Portfolio_Contribution_Schema_v1.0).\n" + dump(mpc), encoding="utf-8")

    # --- thesis.md ---
    vec = " + ".join(f"{ax}={v['current']}" for ax, v in d["states"].items())
    (out / "thesis.md").write_text(f"""# {c['company']} ({tk}, {c['exchange']}): фактическая позиция

Бумага в портфеле владельца (см. `portfolio/_portfolio.yaml`, счёт и количество там). Тезис владельца в системе не
записан: позиция унаследована из портфеля, собранного до системы. Модель компании (оси состояния, KPI, триггеры
переходов, входы MPC) получена от другой LLM {TODAY} (партия 1) и лежит в `states.yaml`, `kpis.yaml`, `triggers.yaml`,
`mpc_inputs.yaml`. Значения KPI — до сверки с первоисточниками (`verified: false`).

**Текущий вектор состояний (снимок LLM на {TODAY}):** {vec}.

**Что дальше по конвейеру:** проверка фактов → калибровка reverse valuation и условного MC (после MC v1.1) → MPC →
оптимизатор. Решение Core/Challenger/Watch — только после этого; сейчас `role.current: null`.
""", encoding="utf-8")

    # --- state.json ---
    st = {"updated": f"{TODAY}T00:30:00Z", "price": {"last": Q[tk]["price"], "last_at": "2026-09-18", "zone": None},
          "fired": [], "events_reported": [], "pending_verification": [],
          "notes": f"Папка создана {TODAY} по партии 1 моделей компаний; значения KPI ждут сверки (задание facts-verify).",
          "route": {"current": "vector", "done_steps": [], "changed_at": TODAY, "note": "фазы стратегии владельца не заданы; ведётся только вектор состояний"},
          "info_log": [{"timestamp": f"{TODAY}T00:30:00Z", "kind": "onboarding",
                        "summary": f"Модель компании {tk} v1.0 принята от другой LLM (партия 1); вектор {vec}; KPI не сверены"}],
          "scenario_state": {ax: {"state": v["current"], "since": TODAY, "evidence": v.get("current_evidence", []),
                                  "source": ", ".join(sources.get(r, r) for r in v.get("source_refs", [])), "verified": False}
                             for ax, v in d["states"].items()},
          "state_transitions": [], "kpi_observations": [], "calc_runs": []}
    (out / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(tk, "→", out, "| осей", len(axes), "| KPI", len(kp), "| триггеров", len(trig))

# --- _portfolio.yaml: ответы владельца 21.09 ---
p = Path("portfolio/_portfolio.yaml"); s = p.read_text(encoding="utf-8")
rep = [
    ('      - {id: P2, currency: USD, amount: null, fx_to_base: 1.0, source: "owner — сумма не сообщена"}\n',
     '      - {id: P2, currency: USD, amount: 0.0, fx_to_base: 1.0, source: "owner 2026-09-21: кэш второго счёта — ноль"}\n'),
    ("      account: null                 # владелец не указал, в каком из двух портфелей (уточнить)\n",
     "      account: P1                   # владелец 21.09.2026\n"),
    ('      benchmark_id: AI_COMPUTE_BENCHMARK_PENDING\n      status: pending_owner_selection\n      candidates_note: "нет чистого ETF; варианты — равновзвешенная корзина NBIS/CRWV (совпадает с позициями) или SOX как прокси"\n',
     '      benchmark_id: none\n      status: no_external_benchmark_v1\n      decided_by: "другая LLM (партия 1, 21.09.2026), владелец согласен"\n      reason: "экономика GPU-облаков не представлена ни IGV, ни полупроводниковыми индексами, ни широкими AI-ETF; до методологии AI_COMPUTE_BASKET сектор вне покрытия"\n'),
    ('      benchmark_id: INTERNET_BENCHMARK_PENDING\n      status: pending_owner_selection\n      proposed: {yahoo: XLC, name: "Communication Services Select Sector SPDR"}\n',
     '      benchmark_id: XLC\n      yahoo: XLC\n      name: "Communication Services Select Sector SPDR"\n      type: proxy_etf\n      approved_by_owner: "2026-09-21"\n'),
    ('      benchmark_id: HEALTHCARE_BENCHMARK_PENDING\n      status: pending_owner_selection\n      proposed: {yahoo: XLV, name: "Health Care Select Sector SPDR"}\n',
     '      benchmark_id: XLV\n      yahoo: XLV\n      name: "Health Care Select Sector SPDR"\n      type: proxy_etf\n      approved_by_owner: "2026-09-21"\n'),
    ('      benchmark_id: FINTECH_BENCHMARK_PENDING\n      status: pending_owner_selection\n      proposed: {yahoo: ARKF, name: "ARK Fintech Innovation ETF"}\n',
     '      benchmark_id: ARKF\n      yahoo: ARKF\n      name: "ARK Fintech Innovation ETF"\n      type: proxy_etf\n      approved_by_owner: "2026-09-21"\n'),
]
for a, b in rep:
    assert s.count(a) == 1, a[:60]
    s = s.replace(a, b)
# ссылки на модели компаний у позиций NBIS/NVDA/HOOD
for tk, c in COMPANIES.items():
    for acc in ("P1", "P2"):
        key = f"    - ticker: {tk}\n      account: {acc}\n"
        if key in s:
            blk_end = s.index("      target: {weight: null, target_version: null, effective_from: null}\n", s.index(key)) + len("      target: {weight: null, target_version: null, effective_from: null}\n")
            s = s[:blk_end] + f"      state_vector_ref: portfolio/{c['folder']}/states.yaml\n      company_rules_ref: portfolio/{c['folder']}/triggers.yaml\n" + s[blk_end:]
p.write_text(s, encoding="utf-8"); d_p = yaml.safe_load(s)

# --- пересчёт portfolio_regime с 8 benchmark'ами ---
positions = d_p["portfolio"]["positions"]; merged = {}
for e in positions:
    m = merged.setdefault(e["ticker"], {"ticker": e["ticker"], "sector_id": e["sector_id"], "quantity": 0.0, "price": e["market"]["price"], "price_12m_max": e["market"]["price_12m_max"]})
    m["quantity"] += float(e["quantity"])
bm = {"SEMICONDUCTORS": "^SOX", "SOFTWARE": "IGV", "SPACE": "UFO", "ELECTRIFICATION": "GRID", "ROBOTICS": "ROBO", "INTERNET_PLATFORMS": "XLC", "HEALTHCARE": "XLV", "FINTECH": "ARKF"}
inputs = {"positions": list(merged.values()), "cash": [{"amount": 897.91}, {"amount": 0.0}], "nav_running_max": d_p["machine_outputs"]["current_nav"],
          "sector_benchmarks": {k: {"index": Q[v]["price"], "index_12m_max": Q[v]["max_12m"]} for k, v in bm.items()},
          "as_of": "2026-09-18", "note": "пересчёт первого снимка: кэш P2 = 0 (владелец), benchmark'и XLC/XLV/ARKF приняты, AI_COMPUTE без benchmark"}
req = json.dumps({"model": "portfolio_regime", "inputs": inputs, "seed": 0, "save": True}).encode("utf-8")
run = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:18791/run", data=req, headers={"Content-Type": "application/json"}), timeout=60))
json.dump(run, open("_regime_run2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
o = run["outputs"]; rid = run["run_id"]
print("run2:", rid, "NAV", o["nav_base"], "regime", o["regime"], "weighted_sector", o["drawdowns"]["weighted_sector"], "coverage", o["drawdowns"]["benchmark_coverage"])
print("sectors:", {k: v for k, v in o["drawdowns"]["sectors"].items() if v is not None})

# machine_outputs / nav_history: тот же as_of → заменить снимок
s = p.read_text(encoding="utf-8")
m0 = s.index("\nmachine_outputs:") + 1
w = {x["ticker"]: x["weight_nav"] for x in o["positions"]}
weights = "".join(f"    {t}: {w[t]}\n" for t in sorted(w, key=lambda k: -w[k]))
s = s[:m0] + f'''machine_outputs:                 # последний прогон portfolio_regime (portfolio/_runs/{rid}.json); пересчёт снимка 18.09 после ответов владельца 21.09
  run_id: "{rid}"
  model_version: "{run.get('version')}"
  as_of_prices: "2026-09-18"
  current_nav: {o['nav_base']}
  positions_value_base: {o['positions_value_base']}
  cash_value_base: {o['cash_value_base']}
  current_weights:
{weights}  drawdowns:
    portfolio: {o['drawdowns']['portfolio']}          # первый снимок: истории NAV нет, running max = текущий NAV
    weighted_sector: {o['drawdowns']['weighted_sector']}
    benchmark_coverage: {o['drawdowns']['benchmark_coverage']}   # доля NAV в секторах с утверждённым benchmark
    sectors: {json.dumps({k: v for k, v in o['drawdowns']['sectors'].items() if v is not None})}
  breadth: {json.dumps(o['breadth'])}
  regime: {o['regime']}
  regime_reason: "широта: {o['breadth']['fraction_positions_dd_le_stress']:.0%} бумаг с просадкой ≥25% (порог 25%); взвешенная секторная {o['drawdowns']['weighted_sector']:.1%}; Shock нет: {o['breadth']['fraction_positions_dd_le_shock']:.0%} бумаг ≥40% (порог 25%)"
  constraint_breaches: []
  dry_powder_status: null
  timestamp: "{TODAY}T00:40:00Z"
  caveats:
    - "без секторного benchmark: NBIS/CRWV (AI_COMPUTE — решение v1: внешнего нет), GLD"
    - "просадка портфеля = 0 по построению (первый снимок); накапливается с этого прогона"
'''
s = s.replace('      source_snapshot: "20260920T210151Z-portfolio_regime-b472bc"\n      note: "первый снимок; кэш P2 не учтён"\n',
              f'      source_snapshot: "{rid}"\n      note: "первый снимок (пересчитан 21.09: кэш P2 = 0, 8 benchmark\'ов; первичный прогон …-b472bc)"\n')
p.write_text(s, encoding="utf-8"); yaml.safe_load(s)

# --- _candidates.yaml: стадия company_model ---
c = Path("portfolio/_candidates.yaml"); cs = c.read_text(encoding="utf-8")
for tk, cc in COMPANIES.items():
    i = cs.index(f"  - {{ticker: {tk},"); j = cs.index("\n", i); line = cs[i:j]
    assert "stage: candidate" in line, tk
    line = line.replace("stage: candidate", f"stage: company_model, folder: {cc['folder']}, model_received: \"{TODAY}\"")
    cs = cs[:i] + line + cs[j:]
c.write_text(cs, encoding="utf-8"); yaml.safe_load(cs)
print("batch01 applied")
