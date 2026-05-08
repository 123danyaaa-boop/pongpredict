import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

REQUIREMENT_PATTERNS = [
    r"участник должен",
    r"участник обязан",
    r"необходимо наличие",
    r"требуется подтверждение",
    r"опыт исполнения",
    r"лицензи[яи]",
    r"сертификат\s+соответствия",
    r"финансовое\s+обеспечение",
    r"обеспечение\s+заявки",
    r"обеспечение\s+исполнения\s+контракта",
    r"не\s+менее",
    r"не\s+более",
    r"запрет",
    r"ограничение",
    r"выручка",
    r"среднесписочная\s+численность",
    r"субъект\s+м[сc][пб]",
    r"членство\s+в\s+[сc]ро",
    r"свидетельство\s+[сc]ро",
    r"опыт\s+работы",
    r"штраф",
    r"неустойка",
    r"обеспечительный\s+платёж",
    r"банковская\s+гарантия",
    r"национальный\s+режим",
]

MANDATORY_KEYWORDS = [
    r"обязан", r"должен", r"требуется", r"необходимо",
    r"обязательно", r"в\s+обязательном\s+порядке",
]

CATEGORY_PATTERNS = {
    "QUALIFICATION": [
        r"опыт", r"лицензи", r"сертификат", r"членство\s+в\s+[сc]ро",
        r"свидетельство\s+[сc]ро", r"квалификаци", r"образовани",
        r"деловая\s+репутация", r"персонал", r"специалист",
    ],
    "FINANCIAL": [
        r"обеспечение\s+заявки", r"обеспечение\s+исполнения",
        r"финансовое\s+обеспечение", r"банковская\s+гарантия",
        r"выручка", r"финансов", r"оборот", r"страхование",
        r"обеспечительный\s+платёж",
    ],
    "TECHNICAL": [
        r"технические?\s+характеристики", r"гост", r"стандарт",
        r"технические?\s+условия", r"параметр", r"требования?\s+к\s+качеству",
        r"функциональ", r"характеристики?\s+товара",
    ],
    "DOCUMENTATION": [
        r"копи[яи]", r"выписка", r"справка", r"декларация",
        r"учредительн", r"уставн", r"свидетельство", r"выписка\s+из\s+егрюл",
        r"список\s+документов", r"перечень\s+документов",
    ],
    "RESTRICTION": [
        r"только\s+субъект", r"субъект\s+м[сc][пб]", r"малое\s+предприятие",
        r"национальный\s+режим", r"запрет.*?допуска", r"ограничен.*?участи",
        r"[сc]онко", r"нацрежим",
    ],
}


class DocumentParser:
    def __init__(self):
        self._nlp = None
        self._nlp_loaded = False

    def _get_nlp(self):
        if self._nlp_loaded:
            return self._nlp
        try:
            import spacy
            self._nlp = spacy.load("ru_core_news_lg")
            logger.info("spaCy ru_core_news_lg loaded")
        except Exception:
            try:
                import spacy
                self._nlp = spacy.load("ru_core_news_sm")
                logger.warning("Falling back to ru_core_news_sm")
            except Exception:
                logger.warning("spaCy Russian model not available; using basic sentence splitting")
                self._nlp = None
        self._nlp_loaded = True
        return self._nlp

    def parse_file(self, file_path: str) -> Dict[str, Any]:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._parse_pdf(path)
        elif suffix in (".docx", ".doc"):
            return self._parse_docx(path)
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
            return {"full_text": text, "pages": [{"number": 1, "text": text}]}

    def _parse_pdf(self, path: Path) -> Dict[str, Any]:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("pdfplumber is required for PDF parsing: pip install pdfplumber")

        pages = []
        full_text_parts = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                pages.append({"number": i, "text": text})
                full_text_parts.append(text)
        return {"full_text": "\n".join(full_text_parts), "pages": pages}

    def _parse_docx(self, path: Path) -> Dict[str, Any]:
        try:
            from docx import Document
        except ImportError:
            raise ImportError("python-docx is required: pip install python-docx")

        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        full_text = "\n".join(paragraphs)
        return {
            "full_text": full_text,
            "pages": [{"number": 1, "text": full_text}],
        }

    def _split_sentences(self, text: str) -> List[str]:
        nlp = self._get_nlp()
        if nlp is not None:
            doc = nlp(text[:100000])
            return [sent.text.strip() for sent in doc.sents if sent.text.strip()]
        # fallback: split on period/newline
        sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
        return [s.strip() for s in sentences if s.strip()]

    def extract_requirements(self, parsed_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
        full_text = parsed_doc.get("full_text", "")
        pages = parsed_doc.get("pages", [{"number": 1, "text": full_text}])

        # Build page index: char_offset → page_number
        page_boundaries: List[tuple] = []
        offset = 0
        for page in pages:
            start = full_text.find(page["text"][:50]) if page["text"] else offset
            if start == -1:
                start = offset
            page_boundaries.append((start, start + len(page["text"]), page["number"]))
            offset = start + len(page["text"])

        sentences = self._split_sentences(full_text)
        requirements = []

        for sentence in sentences:
            sentence_lower = sentence.lower()
            matched_pattern = any(
                re.search(p, sentence_lower) for p in REQUIREMENT_PATTERNS
            )
            if not matched_pattern:
                continue
            if len(sentence) < 15:
                continue

            category = self._classify_category(sentence_lower)
            is_mandatory = any(re.search(kw, sentence_lower) for kw in MANDATORY_KEYWORDS)
            extracted_value = self._extract_numeric_value(sentence)
            risk_level = self._classify_risk(sentence_lower)
            source_page = self._find_page(sentence, full_text, page_boundaries)

            requirements.append({
                "category": category,
                "text": sentence,
                "is_mandatory": is_mandatory,
                "source_page": source_page,
                "extracted_value": extracted_value,
                "risk_level": risk_level,
            })

        logger.info(f"Extracted {len(requirements)} requirements")
        return requirements

    def _classify_category(self, text: str) -> str:
        scores = {cat: 0 for cat in CATEGORY_PATTERNS}
        for cat, patterns in CATEGORY_PATTERNS.items():
            for p in patterns:
                if re.search(p, text):
                    scores[cat] += 1
        best = max(scores, key=lambda c: scores[c])
        if scores[best] == 0:
            return "TECHNICAL"
        return best

    def _classify_risk(self, text: str) -> str:
        high_signals = [
            r"штраф.*?\d+%", r"обеспечение.*?\d+%", r"срок.*?\d+\s*дн",
            r"только.*?м[сc][пб]", r"национальный\s+режим",
        ]
        medium_signals = [
            r"неустойк", r"одностороннее\s+расторжение",
            r"авансирование\s+не\s+предусмотрено",
        ]
        if any(re.search(p, text) for p in high_signals):
            return "HIGH"
        if any(re.search(p, text) for p in medium_signals):
            return "MEDIUM"
        return "LOW"

    def _extract_numeric_value(self, text: str) -> Optional[str]:
        patterns = [
            r"не\s+менее\s+(\d+[\.,]?\d*)\s*(\w+)",
            r"не\s+более\s+(\d+[\.,]?\d*)\s*(\w+)",
            r"(\d+[\.,]?\d*)\s*(лет|год[а-я]*|месяц[а-я]*|дн[её][йя]?|%|руб[л]?|млн|тыс)",
            r"от\s+(\d+[\.,]?\d*)\s*(\w+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text.lower())
            if m:
                return " ".join(g for g in m.groups() if g)
        return None

    def _find_page(
        self,
        sentence: str,
        full_text: str,
        boundaries: List[tuple],
    ) -> int:
        pos = full_text.find(sentence[:40])
        if pos == -1:
            return 1
        for start, end, page_num in boundaries:
            if start <= pos <= end:
                return page_num
        return 1

    def extract_metadata(self, text: str) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}

        nmck_match = re.search(
            r"(?:нмцк|начальн[а-я]+\s+(?:максимальн[а-я]+\s+)?цен[а-я]+)[^\d]*([\d\s]+(?:[.,]\d+)?)\s*(?:руб|тыс|млн)?",
            text.lower(),
        )
        if nmck_match:
            raw = nmck_match.group(1).replace(" ", "").replace(",", ".")
            try:
                metadata["initial_price"] = float(raw)
            except ValueError:
                pass

        inn_match = re.search(r"инн\s*[:\s]?\s*(\d{10}|\d{12})", text.lower())
        if inn_match:
            metadata["customer_inn"] = inn_match.group(1)

        number_match = re.search(r"(?:извещение|закупка)[^\d]*(\d{19,22})", text.lower())
        if number_match:
            metadata["external_id"] = number_match.group(1)

        law_match = re.search(r"44[\-\s]?фз|федеральный\s+закон\s+№\s*44", text.lower())
        if law_match:
            metadata["law_type"] = "FZ_44"
        elif re.search(r"223[\-\s]?фз", text.lower()):
            metadata["law_type"] = "FZ_223"

        return metadata
