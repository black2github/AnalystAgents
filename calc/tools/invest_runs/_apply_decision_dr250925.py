"""Запись решения владельца по DR-2026-09-25-01 (25.09.2026): p(TAIWAN_SEIZURE) = 0.10, p(CHIP_COLD_WAR) = 0.07, BASE 0.83 =
«гонка продолжается без паритета и без силового Тайваня». Правки построчно с сохранением байтов:
- portfolio/_portfolio.yaml → owner_decisions: три строки (p_TS, p_CW, правило пересмотра);
- portfolio/_scenarios/TAIWAN_SEIZURE_v1.0.yaml и CHIP_COLD_WAR_v1.0.yaml: probability, probability_status, probability_meta;
- decisions/DR-2026-09-25-01-scenario-probabilities.md: раздел «Решение владельца».
Запуск: python _apply_decision_dr250925.py [--apply]"""
import sys
from pathlib import Path

WS = Path("C:/openclaw-lab/data/workspace-invest"); APPLY = "--apply" in sys.argv


def patch(path: Path, reps: list[tuple[str, str]]) -> None:
    raw = path.read_bytes(); nl = "\r\n" if b"\r\n" in raw else "\n"; s = raw.decode("utf-8").replace("\r\n", "\n")
    for a, b in reps:
        assert s.count(a) == 1, (path.name, a[:60])
        s = s.replace(a, b)
    print(f"- {path.relative_to(WS)}: {len(reps)} правок ({'CRLF' if nl == chr(13) + chr(10) else 'LF'})")
    if APPLY:
        path.write_bytes(s.replace("\n", nl).encode("utf-8"))


SRC = "decisions/DR-2026-09-25-01-scenario-probabilities.md"
# 1) owner_decisions — после строки В4
anchor = ('  - {id: "DR-2026-09-24-01/В4", date: "2026-09-24", ticker: null, question: "кэш (dry powder) 0.5 % NAV ниже минимума 5 % для режима Stress", '
          'decision: "принять нарушение осознанно до отбора бумаг портфеля", review: "2026-10-20 или завершение отбора (что раньше)", source: "decisions/DR-2026-09-24-constraint-gaps-and-capacity.md"}\n')
new = anchor + (
    '  - {id: "DR-2026-09-25-01/p_TS", date: "2026-09-25", ticker: null, question: "вероятность сценария TAIWAN_SEIZURE (ограничения → блокада → конфликт → восстановление) на горизонте калибровки", '
    'decision: "0.10 — середина оценки владельца 8–12 % до конца 2028 для захвата силой или полной блокады (консервативно: у калибровки каждая блокада перерастает в конфликт); вариант V1", '
    'review: "по каталогу признаков фаз TW-F01…F04 и списку владельца (суда береговой охраны и досмотры, мобилизация ro-ro, судьба продажи оружия $14 млрд, темп выпуска Patriot/LRASM); при новой версии сценарной калибровки; не реже раза в квартал", '
    f'source: "{SRC} + decisions/DR-2026-09-25-01-owner-analysis.md"}}\n'
    '  - {id: "DR-2026-09-25-01/p_CW", date: "2026-09-25", ticker: null, question: "вероятность сценария CHIP_COLD_WAR (гонка → граница паритета 2029–2031 → две системы с ценовой конкуренцией ускорителей)", '
    'decision: "0.07 — в пересечении оценок владельца: полная цепочка 3–7 %, паритет в передовых чипах 5–10 %; вариант V1", '
    'review: "по каталогу CW-F01…F06 и списку владельца (первые чипы на китайской EUV-машине, тиражи китайских литографов); при новой версии калибровки; не реже раза в квартал", '
    f'source: "{SRC} + decisions/DR-2026-09-25-01-owner-analysis.md"}}\n'
    '  - {id: "DR-2026-09-25-01/BASE", date: "2026-09-25", ticker: null, question: "что означает остаток BASE = 0.83", '
    'decision: "гонка (холодная война в полупроводниках и военном ИИ с госрасходами с обеих сторон) уже идёт (~90 % по оценке владельца) и есть базовый режим, а не сценарий: BASE 0.83 = гонка продолжается без паритета и без силового Тайваня; сценарий затянувшейся гонки не заказывается; к IMMA — вопрос, содержат ли базовые калибровки гонку (госзаказ, reshoring, ставки)", '
    'review: "вместе с p_TS / p_CW; карантин и частичная блокада (15–20 % по оценке владельца) пока входят в BASE — заказ TAIWAN_QUARANTINE у IMMA", '
    f'source: "{SRC}"}}\n')
patch(WS / "portfolio" / "_portfolio.yaml", [(anchor, new)])

# 2) сценарные калибровки
for sid, p, why in (("TAIWAN_SEIZURE", "0.1", "Owner judgment 2026-09-25 (DR-2026-09-25-01): 0.10 = midpoint of owner estimate 8-12% by end-2028 for seizure by force or full blockade; conservative because the calibration escalates every blockade into conflict. Review rule: TW-F01..F04 fact catalog + owner watch list; each scenario reissue; at least quarterly."),
                     ("CHIP_COLD_WAR", "0.07", "Owner judgment 2026-09-25 (DR-2026-09-25-01): 0.07 = intersection of owner estimates (full chain 3-7%, leading-edge parity 5-10%); the semiconductor/military-AI race itself is treated as BASE (~90% already under way), so BASE 0.83 = race continues without parity and without Taiwan seizure. Review rule: CW-F01..F06 + owner watch list; each reissue; at least quarterly.")):
    f = WS / "portfolio" / "_scenarios" / f"{sid}_v1.0.yaml"
    old_r = {"TAIWAN_SEIZURE": "Probability intentionally left to owner; calibration defines conditional outcomes only.",
             "CHIP_COLD_WAR": "Owner explicitly requested separate probability judgment; calibration must not infer it."}[sid]
    patch(f, [(f"probability: null\nprobability_status: pending_owner_judgment\nprobability_meta:\n  provenance: owner_judgment\n  rationale: {old_r}\n",
               f"probability: {p}\nprobability_status: owner_judgment\nprobability_meta:\n  provenance: owner_judgment\n  rationale: {why}\n")])

# 3) DR — раздел решения
dr = WS / SRC
patch(dr, [("Дата: 25.09.2026. Статус: ожидает решения владельца.", "Дата: 25.09.2026. Статус: РЕШЕНО владельцем 25.09.2026 (см. раздел «Решение владельца» внизу)."),
           ("## Что нужно от владельца\n1. Вариант (V0…V3). 2. При V1/V2 — p(TS) и p(CW) (или диапазоны) и одна фраза обоснования (для provenance owner_judgment).\n3. Согласие с правилом пересмотра п. 5 или его правка.\n",
            "## Решение владельца (25.09.2026)\n"
            "Вариант **V1**. p(TAIWAN_SEIZURE) = **0.10** (середина оценки 8–12 % до конца 2028 для захвата силой или полной блокады;\n"
            "консервативно — у калибровки каждая блокада перерастает в конфликт). p(CHIP_COLD_WAR) = **0.07** (пересечение оценок: полная\n"
            "цепочка 3–7 %, паритет в передовых чипах 5–10 %). Ключевое уточнение владельца: «холодная война» в полупроводниках и военном\n"
            "ИИ уже идёт (~90 %) и является базовым режимом, а не сценарием — **BASE 0.83 читается как «гонка продолжается без паритета\n"
            "и без силового Тайваня»**. Правило пересмотра п. 5 принято, дополнено списком признаков владельца (суда береговой охраны и\n"
            "досмотры; мобилизация ro-ro; судьба продажи оружия $14 млрд; темп выпуска Patriot/LRASM; первые чипы на китайской EUV;\n"
            "тиражи китайских литографов). Разбор владельца — `DR-2026-09-25-01-owner-analysis.md`. Следствия: карантин/частичная\n"
            "блокада (15–20 %) пока в BASE → заказ IMMA TAIWAN_QUARANTINE; к IMMA вопросы — содержат ли базовые калибровки гонку;\n"
            "составной сценарий (прорыв Китая снимает китайский сдерживающий фактор). Запись: `_portfolio.yaml → owner_decisions`\n"
            "(DR-2026-09-25-01/p_TS, /p_CW, /BASE), `portfolio/_scenarios/*_v1.0.yaml → probability` (owner_judgment).\n")])
print("режим:", "ЗАПИСЬ" if APPLY else "сухой прогон")
