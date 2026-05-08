import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

CATEGORY_WEIGHTS = {
    "QUALIFICATION": 0.35,
    "FINANCIAL": 0.25,
    "TECHNICAL": 0.30,
    "DOCUMENTATION": 0.10,
    "RESTRICTION": 0.00,  # restrictions are handled separately
}

OKPD2_DESCRIPTIONS = {
    "26": "программное обеспечение разработка IT информационные технологии",
    "62": "разработка программного обеспечения IT-услуги программирование",
    "63": "информационные технологии IT-сервис техническая поддержка",
    "72": "научные исследования разработки",
    "33": "ремонт монтаж оборудования",
    "86": "медицинские услуги здравоохранение",
    "41": "строительство зданий",
    "42": "строительство инженерных сооружений",
    "43": "специализированные строительные работы",
    "38": "сбор переработка отходов",
    "25": "металлические изделия оборудование",
    "28": "машины оборудование промышленные",
    "29": "автомобили транспортные средства",
    "47": "розничная торговля",
    "49": "транспорт перевозки",
    "85": "образование обучение",
    "80": "охрана безопасность",
    "81": "обслуживание зданий уборка клининг",
}


class RequirementMatcher:
    def __init__(self):
        self._model = None
        self._model_loaded = False

    def _get_model(self):
        if self._model_loaded:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
            logger.info("SentenceTransformer model loaded")
        except Exception as e:
            logger.warning(f"SentenceTransformer not available ({e}); using TF-IDF fallback")
            self._model = None
        self._model_loaded = True
        return self._model

    def _encode_texts(self, texts: List[str]) -> np.ndarray:
        model = self._get_model()
        if model is not None:
            return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        # TF-IDF fallback
        from sklearn.feature_extraction.text import TfidfVectorizer
        vec = TfidfVectorizer(max_features=300, analyzer="char_wb", ngram_range=(2, 4))
        return vec.fit_transform(texts).toarray().astype(np.float32)

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        a_norm = np.linalg.norm(a, axis=1, keepdims=True)
        b_norm = np.linalg.norm(b, axis=1, keepdims=True)
        a_safe = np.where(a_norm == 0, 1e-10, a_norm)
        b_safe = np.where(b_norm == 0, 1e-10, b_norm)
        a_normalized = a / a_safe
        b_normalized = b / b_safe
        return a_normalized @ b_normalized.T

    def _company_capabilities_text(self, company: Dict[str, Any]) -> List[str]:
        capabilities = []
        past_contracts = company.get("past_contracts") or []
        for contract in past_contracts:
            subject = contract.get("subject", "")
            year = contract.get("year", "")
            amount = contract.get("amount", "")
            if subject:
                capabilities.append(
                    f"опыт исполнения контракта: {subject} {year} год сумма {amount} рублей"
                )

        licenses = company.get("licenses") or []
        if isinstance(licenses, list):
            for lic in licenses:
                if isinstance(lic, dict):
                    capabilities.append(
                        f"лицензия сертификат: {lic.get('name', '')} {lic.get('type', '')}"
                    )
                else:
                    capabilities.append(f"лицензия сертификат: {lic}")
        elif isinstance(licenses, dict):
            for k, v in licenses.items():
                capabilities.append(f"лицензия: {k} {v}")

        okpd2_codes = company.get("okpd2_codes") or []
        if isinstance(okpd2_codes, list):
            for code in okpd2_codes:
                code_str = str(code)
                prefix = code_str[:2]
                desc = OKPD2_DESCRIPTIONS.get(prefix, code_str)
                capabilities.append(f"виды деятельности ОКПД2 {code_str}: {desc}")
        elif isinstance(okpd2_codes, dict):
            for code, desc in okpd2_codes.items():
                capabilities.append(f"виды деятельности ОКПД2 {code}: {desc}")

        revenue = company.get("annual_revenue")
        if revenue:
            capabilities.append(
                f"годовая выручка {revenue} рублей финансовая устойчивость"
            )

        founding_year = company.get("founding_year")
        if founding_year:
            years_active = datetime.now().year - int(founding_year)
            capabilities.append(
                f"опыт работы {years_active} лет компания основана в {founding_year}"
            )

        staff_count = company.get("staff_count")
        if staff_count:
            capabilities.append(
                f"среднесписочная численность сотрудников {staff_count} человек персонал"
            )

        if company.get("smp_status"):
            capabilities.append(
                "субъект малого предпринимательства МСП малое предприятие СМП"
            )

        name = company.get("name", "")
        capabilities.append(
            f"компания организация {name} предоставляет услуги выполняет работы поставляет товары"
        )

        if not capabilities:
            capabilities.append("организация участник закупки")

        return capabilities

    def match(
        self,
        requirements: List[Dict[str, Any]],
        company: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not requirements:
            return self._empty_analysis()

        capabilities = self._company_capabilities_text(company)
        req_texts = [r["text"] for r in requirements]

        try:
            req_embeddings = self._encode_texts(req_texts)
            cap_embeddings = self._encode_texts(capabilities)
            sim_matrix = self._cosine_similarity(req_embeddings, cap_embeddings)
        except Exception as e:
            logger.error(f"Embedding failed: {e}; using zero similarity")
            sim_matrix = np.zeros((len(requirements), len(capabilities)))

        SIMILARITY_THRESHOLD = 0.55

        matched: List[Dict] = []
        missing: List[Dict] = []

        category_scores: Dict[str, List[float]] = {
            cat: [] for cat in CATEGORY_WEIGHTS
        }

        for i, req in enumerate(requirements):
            max_sim = float(np.max(sim_matrix[i])) if sim_matrix.shape[1] > 0 else 0.0
            category = req.get("category", "TECHNICAL")
            is_matched = max_sim >= SIMILARITY_THRESHOLD

            if category in category_scores:
                category_scores[category].append(1.0 if is_matched else 0.0)

            entry = {
                "text": req["text"][:200],
                "category": category,
                "is_mandatory": req.get("is_mandatory", False),
                "similarity": round(max_sim, 3),
                "risk_level": req.get("risk_level", "LOW"),
            }

            if is_matched:
                matched.append(entry)
            else:
                missing.append(entry)

        scores: Dict[str, float] = {}
        for cat, values in category_scores.items():
            scores[cat] = float(np.mean(values)) if values else 1.0

        overall = sum(
            scores.get(cat, 1.0) * weight
            for cat, weight in CATEGORY_WEIGHTS.items()
            if cat != "RESTRICTION"
        )
        weight_sum = sum(w for c, w in CATEGORY_WEIGHTS.items() if c != "RESTRICTION")
        overall = overall / weight_sum if weight_sum > 0 else 0.0

        restriction_reqs = [r for r in requirements if r.get("category") == "RESTRICTION"]
        if restriction_reqs:
            company_is_smp = company.get("smp_status", False)
            for rr in restriction_reqs:
                import re
                if re.search(r"только.*?м[сc][пб]|субъект.*?м[сc][пб]", rr["text"].lower()):
                    if not company_is_smp:
                        overall = min(overall, 0.2)
                        missing.append({
                            "text": rr["text"][:200],
                            "category": "RESTRICTION",
                            "is_mandatory": True,
                            "similarity": 0.0,
                            "risk_level": "HIGH",
                        })

        recommendation = self._recommend(overall, missing)

        return {
            "overall_match_score": round(overall, 3),
            "qualification_score": round(scores.get("QUALIFICATION", 1.0), 3),
            "financial_score": round(scores.get("FINANCIAL", 1.0), 3),
            "technical_score": round(scores.get("TECHNICAL", 1.0), 3),
            "documentation_score": round(scores.get("DOCUMENTATION", 1.0), 3),
            "matched_requirements": matched,
            "missing_requirements": missing,
            "recommendation": recommendation,
            "analysis_notes": self._generate_notes(overall, matched, missing, scores),
        }

    def _recommend(self, score: float, missing: List[Dict]) -> str:
        mandatory_missing = sum(1 for r in missing if r.get("is_mandatory"))
        if score >= 0.70 and mandatory_missing == 0:
            return "PARTICIPATE"
        if score >= 0.45 and mandatory_missing <= 2:
            return "CONSIDER"
        return "AVOID"

    def _generate_notes(
        self,
        overall: float,
        matched: List,
        missing: List,
        scores: Dict,
    ) -> str:
        mandatory_missing = [r for r in missing if r.get("is_mandatory")]
        notes = [f"Общий балл соответствия: {overall:.1%}."]
        if mandatory_missing:
            notes.append(
                f"Обязательных невыполненных требований: {len(mandatory_missing)}."
            )
        weakest = min(
            ((c, s) for c, s in scores.items() if c in CATEGORY_WEIGHTS and CATEGORY_WEIGHTS[c] > 0),
            key=lambda x: x[1],
            default=None,
        )
        if weakest:
            notes.append(f"Слабейшая категория: {weakest[0]} ({weakest[1]:.1%}).")
        return " ".join(notes)

    def _empty_analysis(self) -> Dict[str, Any]:
        return {
            "overall_match_score": 1.0,
            "qualification_score": 1.0,
            "financial_score": 1.0,
            "technical_score": 1.0,
            "documentation_score": 1.0,
            "matched_requirements": [],
            "missing_requirements": [],
            "recommendation": "CONSIDER",
            "analysis_notes": "Требования не извлечены.",
        }
