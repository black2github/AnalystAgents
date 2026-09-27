"""Запись решения владельца по DR-2026-09-25-02 (27.09.2026): вариант V1, p(TAIWAN_QUARANTINE) = 0.175, BASE = 1 − 0.10 − 0.07 − 0.175 = 0.655.
Правки построчно с сохранением байтов: _portfolio.yaml → owner_decisions (одна строка после /BASE), TAIWAN_QUARANTINE_v1.0.yaml →
probability/status/meta (rationale в кавычках — двоеточия), DR-02 → раздел «Решение владельца». Запуск: python _apply_decision_dr250925_02.py [--apply]"""
import re
import sys
from pathlib import Path

WS = Path("C:/openclaw-lab/data/workspace-invest"); APPLY = "--apply" in sys.argv


def patch(path: Path, reps: list[tuple[str, str]], regex: bool = False) -> None:
    raw = path.read_bytes(); nl = "\r\n" if b"\r\n" in raw else "\n"; s = raw.decode("utf-8").replace("\r\n", "\n")
    for a, b in reps:
        if regex:
            assert len(re.findall(a, s, flags=re.M | re.S)) == 1, (path.name, a[:60]); s = re.sub(a, b, s, count=1, flags=re.M | re.S)
        else:
            assert s.count(a) == 1, (path.name, a[:60]); s = s.replace(a, b)
    print(f"- {path.relative_to(WS)}: {len(reps)} правок")
    if APPLY:
        path.write_bytes(s.replace("\n", nl).encode("utf-8"))


SRC = "decisions/DR-2026-09-25-02-quarantine-probability.md"
anchor_re = r'(  - \{id: "DR-2026-09-25-01/BASE", date: "2026-09-25",[^\n]*\}\n)'
new_line = ('  - {id: "DR-2026-09-25-02/p_Q", date: "2026-09-27", ticker: null, question: "вероятность сценария TAIWAN_QUARANTINE (серая зона: ограничения → карантин береговой охраны / частичная блокада → нормализация или заморозка; без конфликта) на горизонте калибровки", '
            'decision: "0.175 — середина оценки владельца 15–20 % до конца 2028 для карантина / частичной блокады; вариант V1; BASE = 0.655 (гонка без паритета, без силового Тайваня и без карантина)", '
            'review: "по каталогу признаков TQ-F01…F08 (суда береговой охраны и досмотры, ro-ro, пакет вооружений $14 млрд, Patriot/LRASM, страховые ставки, задержки TSMC, ADIZ, портовая логистика); при новой версии калибровки (в т. ч. scope v1.1); не реже раза в квартал — правило DR-2026-09-25-01 п. 5 распространено на карантин", '
            f'source: "{SRC}"}}\n')
patch(WS / "portfolio" / "_portfolio.yaml", [(anchor_re, r"\1" + new_line.replace("\\", "\\\\"))], regex=True)
patch(WS / "portfolio" / "_scenarios" / "TAIWAN_QUARANTINE_v1.0.yaml",
      [(r"^probability: null\nprobability_status: pending_owner_judgment\nprobability_meta:\n  provenance: owner_judgment\n  rationale: [^\n]*\n",
        'probability: 0.175\nprobability_status: owner_judgment\nprobability_meta:\n  provenance: owner_judgment\n  rationale: "Owner judgment 2026-09-27 (DR-2026-09-25-02, variant V1): 0.175 = midpoint of owner estimate 15-20% by end-2028 for a coast-guard quarantine / partial blockade without armed conflict; mutually exclusive with TAIWAN_SEIZURE (0.10) and CHIP_COLD_WAR (0.07), BASE residual 0.655. Review rule: TQ-F01..F08 fact catalog; each scenario reissue (incl. scope v1.1); at least quarterly."\n')],
      regex=True)
patch(WS / SRC, [("Дата: 25.09.2026 (ночь). Статус: ожидает решения владельца.", "Дата: 25.09.2026 (ночь). Статус: РЕШЕНО владельцем 27.09.2026 — вариант V1, p(Q) = 0.175 (см. раздел «Решение владельца» внизу)."),
                 ("## Что нужно от владельца\n1. Вариант (V0…V3). 2. При V1/V2 — значение p(Q) и одна фраза обоснования (для provenance owner_judgment).\n3. Согласие, что правило пересмотра из DR-2026-09-25-01 п. 5 действует и для карантина (признаки TQ-F01…F08).\n",
                  "## Решение владельца (27.09.2026)\nВариант **V1**: p(TAIWAN_QUARANTINE) = **0.175** (середина оценки 15–20 % до конца 2028). Набор GEOTECH_REGIME_8Y_V1: TAIWAN_SEIZURE 0.10,\n"
                  "CHIP_COLD_WAR 0.07, TAIWAN_QUARANTINE 0.175, **BASE 0.655** — «гонка продолжается без паритета, без силового Тайваня и без карантина».\n"
                  "Правило пересмотра DR-2026-09-25-01 п. 5 распространено на карантин (признаки TQ-F01…F08). Запись: `_portfolio.yaml → owner_decisions`\n"
                  "(DR-2026-09-25-02/p_Q), `portfolio/_scenarios/TAIWAN_QUARANTINE_v1.0.yaml → probability` (owner_judgment). Следствия: смесь четырёх\n"
                  "сценариев становится нормативной; ScenarioConcentration применима (два adverse-сценария) — при 0.175 ≈ 55 %, warning, лимит 60 %\n"
                  "не нарушен; заход 6 оптимизатора — на смеси 0.10 / 0.07 / 0.175.\n")])
print("режим:", "ЗАПИСЬ" if APPLY else "сухой прогон")
