"""Приём партии моделей компаний от другой LLM: <TICKER>_company_state_v1.0.yaml (Downloads) → portfolio/<папка>/ в формате дозора.
Использование: python _apply_batch.py <share_url> TICKER:папка:компания:биржа:sector_id [...]
Поддерживает оба формата LLM: партия 1 (states=dict осей, kpis=list, triggers=list) и партия 2 (states.axes, kpis.items, triggers.items)."""
import json, shutil, sys
from pathlib import Path
import yaml

D = Path("C:/Users/alexe/Downloads")
Q = json.load(open("_quotes_2026-09-20.json", encoding="utf-8"))
TODAY = "2026-09-21"
SHARE = sys.argv[1]
AXIS_RU = {
    "Incretin_Demand": "спрос на инкретины (Mounjaro/Zepbound)", "Pricing_Access": "цены и доступ (возмещение)",
    "Manufacturing_Expansion": "расширение производства", "Pipeline_Diversification": "диверсификация пайплайна",
    "Cash_Economics": "денежная экономика (OCF, capex, FCF)",
    "Ad_Monetization": "монетизация рекламы", "User_Engagement": "аудитория и вовлечённость", "FoA_Profitability": "прибыльность Family of Apps",
    "AI_Capital_Intensity": "капиталоёмкость ИИ (capex к выручке)", "Reality_Labs_Drag": "убытки Reality Labs",
    "Demand_Visibility": "видимость спроса (guidance, заказы)", "EUV_Adoption": "доля EUV в продажах систем", "Margin_Execution": "маржа и исполнение",
    "China_Export_Exposure": "экспозиция к Китаю и экспортные ограничения", "Installed_Base_Resilience": "устойчивость сервисного слоя (Installed Base)",
    "Electron_Cadence": "каденция пусков Electron", "Neutron_Development": "разработка Neutron (первый пуск, повторное использование)",
    "Space_Systems_Scale": "масштаб космических систем (Space Systems)", "Backlog_Visibility": "видимость backlog", "Capital_and_Integration": "капитал и интеграция поглощений",
    "Cloud_AI_Demand": "спрос на облако и ИИ (Azure)", "Software_Monetization": "монетизация ПО (Copilot, M365)", "Cloud_Margin": "маржа облака",
    "Contracted_Demand": "законтрактованный спрос (RPO)", "Revenue_Growth": "рост выручки", "Expansion_Retention": "расширение и удержание (NRR)",
    "Profitability_Cash": "прибыльность и денежный поток", "AI_Edge_Monetization": "монетизация ИИ на edge (Workers AI)",
    "US_Commercial_AIP_Monetization": "монетизация AIP в коммерческом сегменте США", "US_Government_Demand": "спрос госзаказчиков США",
    "Geographic_Concentration": "географическая концентрация (доля США / международный сегмент)",
    "Constellation_Deployment": "развёртывание группировки (спутники на орбите, каденция запусков)", "Commercial_Contracting": "коммерческие контракты с операторами",
    "Service_Monetization": "монетизация сервиса SpaceMobile (выручка от услуг)", "Regulatory_Spectrum": "регуляторные разрешения и спектр (FCC)", "Funding_Dilution": "финансирование и размытие капитала",
    "Electrical_Americas_Demand": "спрос Electrical Americas (заказы, backlog)", "Electrical_Global_Demand": "спрос Electrical Global", "Organic_Growth": "органический рост и guidance",
    "Margin_Execution": "маржа и исполнение", "Portfolio_Integration": "интеграция поглощений и долг",
    "Demand_Contracting": "спрос и законтрактованность (backlog)",
}

def dump(obj):
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, width=120)

def load_fixed(tk):
    s = (D / f"{tk}_company_state_v1.0.yaml").read_text(encoding="utf-8")
    if tk == "LLY":  # синтаксическая ошибка в файле LLM: note внутри списка taxonomy_gap
        s = s.replace('    note: "MPC 16-driver taxonomy intentionally understates', '  taxonomy_gap_note: "MPC 16-driver taxonomy intentionally understates', 1)
    return yaml.safe_load(s), s

def norm(d):
    st = d["states"]; axes = st["axes"] if "axes" in st else st
    kp = d["kpis"]; kpis = kp["items"] if isinstance(kp, dict) and "items" in kp else (kp["kpis"] if isinstance(kp, dict) else kp)
    zone_sem = kp.get("zone_semantics") if isinstance(kp, dict) else None
    tr = d["triggers"]; trigs = tr["items"] if isinstance(tr, dict) and "items" in tr else (tr["triggers"] if isinstance(tr, dict) else tr)
    rules = tr.get("rules") if isinstance(tr, dict) else None
    return axes, kpis, zone_sem, trigs, rules

for spec in sys.argv[2:]:
    tk, folder, company, exchange, sector = spec.split(":")
    d, raw = load_fixed(tk)
    axes_src, kpis_src, zone_sem, trigs_src, rules = norm(d)
    out = Path("portfolio") / folder; out.mkdir(parents=True, exist_ok=True)
    Path("inbox/received").mkdir(parents=True, exist_ok=True)
    (Path("inbox/received") / f"{tk}_company_state_v1.0.yaml").write_text(raw, encoding="utf-8")  # копия (с правкой синтаксиса для LLY)
    sources = d.get("sources", {})
    src_note = f"inbox/received/{tk}_company_state_v1.0.yaml (другая LLM, {TODAY}, share {SHARE})"

    axes = {}
    for ax, v in axes_src.items():
        axes[ax] = {"name": ax.replace("_", " "), "name_ru": AXIS_RU.get(ax, ax),
                    "states": {code: {"name": st.get("name"), "criteria": st.get("criteria")} for code, st in v["states"].items()},
                    "current": v["current"], "current_evidence": v.get("current_evidence", []), "source_refs": v.get("source_refs", [])}
        for opt in ("current_note", "note"):
            if opt in v: axes[ax][opt] = v[opt]
    states = {"version": "1.0", "artifact": f"{tk} State Vector", "as_of": TODAY, "ticker": tk, "source_artifact": src_note,
              "purpose": "Оси и состояния компании. Условия переходов — в triggers.yaml (поле transition). Текущий вектор — state.json → scenario_state.",
              "semantics": d.get("semantics") or d.get("source_policy") or {}, "sources": sources, "axes": axes}
    (out / "states.yaml").write_text(f"# Вектор состояний {tk} (оси и состояния). Переходы — triggers.yaml, текущий вектор — state.json.\n" + dump(states), encoding="utf-8")

    kp = []
    for k in kpis_src:
        e = {"id": k["id"], "name": k["name"], "unit": k.get("unit"), "period": k.get("period"),
             "source": "SEC" if "sec.gov" in str(k.get("source", "")) else "IR",
             "thresholds": k.get("zones"), "last_value": k.get("current_value", k.get("current_value_range")),
             "last_date": k.get("as_of"), "source_url": k.get("source"), "verified": False}
        for opt in ("formula", "note", "source_channel", "sec_mirror", "ir_document", "ir_landing_page", "value_type", "target_date"):
            if opt in k: e[opt] = k[opt]
        kp.append(e)
    kpis = {"version": "1.0", "artifact": f"{tk} KPI Dashboard", "as_of": TODAY, "ticker": tk, "max_critical_kpis": 10,
            "source_artifact": src_note, "zone_semantics": zone_sem or {"thresholds_provenance": "model_assumption"},
            "source_policy": {"primary": ["SEC", f"{company} Investor Relations"], "secondary": ["Yahoo Finance"],
                              "rule": "Last value без подтверждённого источника (verified: true) не используется для перехода состояния."},
            "critical_kpis": kp}
    (out / "kpis.yaml").write_text(f"# KPI {tk} с порогами Green/Yellow/Red. История — state.json → kpi_observations.\n" + dump(kpis), encoding="utf-8")

    trig = []
    for t in trigs_src:
        fr, to = t["transition"]["from"], t["transition"]["to"]
        e = {"id": t["id"], "class": "event", "step": "vector", "axis": t["axis"], "transition": {"from": fr, "to": to},
             "level": t.get("level", "E2"), "kpis": t.get("kpis", []), "condition": t["condition"], "period": t.get("period"),
             "source": "первичный источник по kpis.yaml (SEC 10-Q/10-K/6-K, IR)",
             "action": f"Зафиксировать переход {t['axis']} {fr}→{to} в state.json (state_transitions, scenario_state) и отправить Decision Request владельцу; инвестиционное действие не предопределено",
             "automation": None, "status": "planned", "fired": []}
        for opt in ("note", "notes"):
            if opt in t: e[opt] = t[opt]
        trig.append(e)
    hdr = f"""# Реестр триггеров: {company} ({tk})
# Единственный нормативный дом того, ЧТО отслеживаем. Источник: {src_note}.
# Классы: event | price | calendar | digest. Статусы: active | planned | due | done | dropped. Все пороги — model_assumption.
# Тезис владельца по этой бумаге не записан: позиция фактическая (унаследована), см. thesis.md.
"""
    reg = {"meta": {"ticker": tk, "company": company, "exchange": exchange, "yahoo_symbol": tk, "registry_updated": TODAY,
                    "source_artifact": src_note,
                    "price_source": f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?range=1d&interval=1d (поле meta.regularMarketPrice)",
                    "price_at_registry": Q[tk]["price"], "position": "фактическая позиция владельца, см. portfolio/_portfolio.yaml"},
           "automations": {"_note": "дозор событий по этим триггерам ещё не заведён (очередь); вечерняя сводка обходит папку"},
           "route": {"steps": [{"id": "vector", "kind": "axis", "name": "Вектор состояний по осям states.yaml — фазы стратегии владельца не заданы"}]},
           "rules": rules or {"evidence_required": True, "pending_verification_blocks_transition": True, "trigger_not_decision": True},
           "triggers": trig}
    (out / "triggers.yaml").write_text(hdr + dump(reg), encoding="utf-8")

    mpc = {"version": "1.0", "ticker": tk, "artifact": "mpc_inputs", "as_of": TODAY, "source_artifact": src_note, **d["mpc_inputs"]}
    (out / "mpc_inputs.yaml").write_text(f"# Входы MPC для {tk}: вектор экспозиций по драйверам и failure modes (Marginal_Portfolio_Contribution_Schema_v1.0).\n" + dump(mpc), encoding="utf-8")

    vec = " + ".join(f"{ax}={v['current']}" for ax, v in axes_src.items())
    (out / "thesis.md").write_text(f"""# {company} ({tk}, {exchange}): фактическая позиция

Бумага в портфеле владельца (см. `portfolio/_portfolio.yaml`, счёт и количество там). Тезис владельца в системе не
записан: позиция унаследована из портфеля, собранного до системы. Модель компании (оси состояния, KPI, триггеры
переходов, входы MPC) получена от другой LLM {TODAY} и лежит в `states.yaml`, `kpis.yaml`, `triggers.yaml`,
`mpc_inputs.yaml`. Значения KPI — до сверки с первоисточниками (`verified: false`).

**Текущий вектор состояний (снимок LLM на {TODAY}):** {vec}.

**Что дальше по конвейеру:** проверка фактов → калибровка reverse valuation и условного MC (после MC v1.1) → MPC →
оптимизатор. Решение Core/Challenger/Watch — только после этого; сейчас `role.current: null`.
""", encoding="utf-8")

    st = {"updated": f"{TODAY}T06:30:00Z", "price": {"last": Q[tk]["price"], "last_at": "2026-09-18", "zone": None},
          "fired": [], "events_reported": [], "pending_verification": [],
          "notes": f"Папка создана {TODAY} по партии моделей компаний; значения KPI ждут сверки (задание facts-verify).",
          "route": {"current": "vector", "done_steps": [], "changed_at": TODAY, "note": "фазы стратегии владельца не заданы; ведётся только вектор состояний"},
          "info_log": [{"timestamp": f"{TODAY}T06:30:00Z", "kind": "onboarding", "summary": f"Модель компании {tk} v1.0 принята от другой LLM; вектор {vec}; KPI не сверены"}],
          "scenario_state": {ax: {"state": v["current"], "since": TODAY, "evidence": v.get("current_evidence", []),
                                  "source": ", ".join(str(sources.get(r, r)) for r in v.get("source_refs", [])), "verified": False}
                             for ax, v in axes_src.items()},
          "state_transitions": [], "kpi_observations": [], "calc_runs": []}
    (out / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(tk, "→", out, "| осей", len(axes), "| KPI", len(kp), "| триггеров", len(trig), "| вектор", vec)
