import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

RISK_PATTERNS: Dict[str, List[tuple]] = {
    "HIGH": [
        (r"штраф[а-я]*[^.]{0,60}?(\d+[\.,]?\d*)\s*%", "Штрафные санкции {value}% от стоимости контракта"),
        (r"пен[яи]\s*[—\-:]*\s*(\d+[\.,]?\d*)\s*%\s*в\s+день", "Пеня {value}% в день"),
        (r"обеспечение\s+(?:заявки|исполнения)[^.]{0,60}(\d+[\.,]?\d*)\s*%", "Требование обеспечения {value}% от НМЦК"),
        (r"срок[а-я]*\s+(?:исполнения|поставки|выполнения)[^.]{0,60}(\d+)\s*(?:кален|рабоч)?\s*дн", "Сжатые сроки исполнения {value} дней"),
        (r"только\s+(?:для\s+)?субъект[а-я]*\s+м[сc][пб]", "Ограничение участия — только СМП"),
        (r"нацрежим|национальный\s+режим", "Применяется национальный режим (нацрежим)"),
        (r"аванс(?:ирование)?\s+не\s+(?:предусмотрен|предоставляет)", "Авансирование не предусмотрено"),
        (r"субподряд[а-я]*\s+(?:не\s+)?допускается|запрет\s+субподряда", "Запрет/ограничение субподряда"),
        (r"расторжени[еи]\s+в\s+одностороннем\s+порядке", "Одностороннее расторжение контракта заказчиком"),
    ],
    "MEDIUM": [
        (r"неустойк[аи]", "Предусмотрена неустойка"),
        (r"одностороннее\s+расторжение|одностороннем\s+порядке", "Заказчик вправе расторгнуть в одностороннем порядке"),
        (r"авансирование\s+не\s+предусмотрено", "Авансирование отсутствует"),
        (r"банковская\s+гарантия", "Требование банковской гарантии"),
        (r"страхование\s+(?:контракта|ответственности|профессиональной)", "Обязательное страхование"),
        (r"членство\s+в\s+[сc]ро\s+(?:обязательно|необходимо|требуется)", "Обязательное членство в СРО"),
        (r"(?:обязател[а-я]+|требуется?)\s+(?:наличие|предоставление)\s+(?:оригинала|нотариально)", "Нотариальное заверение документов"),
        (r"(\d+)\s*(?:кален|рабоч)?\s*дн[ей]+\s+(?:со|после|от)\s+(?:даты|момента|подписания)", "Сжатые сроки после подписания — {value} дней"),
    ],
    "LOW": [
        (r"гарантийный\s+срок[^.]{0,30}(\d+)\s*(?:лет|месяц|год)", "Гарантийный срок {value} месяцев/лет"),
        (r"страховани[еи]", "Требование страхования"),
        (r"сертификат\s+(?:соответствия|качества|iso)", "Требование сертификатов"),
        (r"(?:паспорт|сертификат)\s+(?:на\s+)?(?:продукцию|товар)", "Документация на продукцию"),
        (r"отчётность\s+(?:ежемесячн|еженедельн|ежеквартальн)", "Периодическая отчётность"),
    ],
}


def _find_page(text_fragment: str, pages: List[Dict]) -> int:
    for page in pages:
        if text_fragment[:30] in page.get("text", ""):
            return page.get("number", 1)
    return 1


class RiskAnalyzer:
    def analyze(
        self,
        tender_text: str,
        requirements: List[Dict[str, Any]],
        pages: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        risk_flags: List[Dict[str, Any]] = []
        pages = pages or []

        text_lower = tender_text.lower()
        sentences = re.split(r"(?<=[.!?])\s+|\n+", tender_text)

        for level, patterns in RISK_PATTERNS.items():
            for pattern, description_template in patterns:
                for sentence in sentences:
                    m = re.search(pattern, sentence.lower())
                    if m:
                        value = m.group(1) if m.lastindex and m.lastindex >= 1 else ""
                        description = description_template.replace("{value}", value)
                        page_num = _find_page(sentence[:30], pages)

                        # Avoid duplicate same-level same-description flags
                        already = any(
                            f["description"] == description and f["level"] == level
                            for f in risk_flags
                        )
                        if not already:
                            risk_flags.append({
                                "level": level,
                                "description": description,
                                "source_text": sentence.strip()[:300],
                                "page": page_num,
                            })

        # Also promote risks from already-classified requirements
        for req in requirements:
            if req.get("risk_level") == "HIGH":
                desc = f"Требование высокого риска: {req['text'][:100]}"
                if not any(f["description"] == desc for f in risk_flags):
                    risk_flags.append({
                        "level": "HIGH",
                        "description": desc,
                        "source_text": req["text"][:300],
                        "page": req.get("source_page", 1),
                    })

        logger.info(f"Risk analysis: {len(risk_flags)} flags found")
        return risk_flags

    def overall_risk_level(self, risk_flags: List[Dict[str, Any]]) -> str:
        if any(f.get("level") == "HIGH" for f in risk_flags):
            return "HIGH"
        if any(f.get("level") == "MEDIUM" for f in risk_flags):
            return "MEDIUM"
        return "LOW"
