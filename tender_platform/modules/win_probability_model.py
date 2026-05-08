import logging
import pickle
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parent.parent / "output" / "win_model.pkl"


def _build_pipeline():
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    try:
        from lightgbm import LGBMClassifier
        clf = LGBMClassifier(n_estimators=100, learning_rate=0.1, random_state=42, verbose=-1)
        logger.info("Using LightGBM classifier")
    except ImportError:
        from sklearn.linear_model import LogisticRegression
        clf = LogisticRegression(max_iter=500, random_state=42)
        logger.info("LightGBM not available; using LogisticRegression")
    return Pipeline([("scaler", StandardScaler()), ("clf", clf)])


class WinProbabilityModel:
    def __init__(self):
        self._pipeline = None
        self._trained = False
        self._load()

    def _load(self):
        if MODEL_PATH.exists():
            try:
                with open(MODEL_PATH, "rb") as f:
                    data = pickle.load(f)
                self._pipeline = data["pipeline"]
                self._trained = data.get("trained", False)
                logger.info("Win probability model loaded from disk")
                return
            except Exception as e:
                logger.warning(f"Failed to load model: {e}")
        self._pipeline = _build_pipeline()
        self._trained = False
        X_syn, y_syn = self._generate_synthetic_data(n=500)
        try:
            self._pipeline.fit(X_syn, y_syn)
            self._trained = True
            self._save()
            logger.info("Win probability model trained on synthetic data")
        except Exception as e:
            logger.error(f"Model training failed: {e}")

    def _save(self):
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({"pipeline": self._pipeline, "trained": self._trained}, f)

    def get_features(
        self,
        analysis: Dict[str, Any],
        tender: Dict[str, Any],
        company: Dict[str, Any],
    ) -> np.ndarray:
        overall = float(analysis.get("overall_match_score") or 0.0)
        qual = float(analysis.get("qualification_score") or 0.0)
        fin = float(analysis.get("financial_score") or 0.0)
        tech = float(analysis.get("technical_score") or 0.0)
        doc_score = float(analysis.get("documentation_score") or 0.0)

        initial_price = float(tender.get("initial_price") or 0)
        revenue = float(company.get("annual_revenue") or 1)
        budget_ratio = initial_price / max(revenue, 1)
        budget_ratio = min(budget_ratio, 10.0)

        founding_year = int(company.get("founding_year") or datetime.now().year)
        experience_years = max(0, datetime.now().year - founding_year)

        past_contracts = company.get("past_contracts") or []
        past_count = len(past_contracts) if isinstance(past_contracts, list) else 0

        tender_okpd = set()
        if tender.get("okpd2_codes"):
            codes = tender["okpd2_codes"]
            if isinstance(codes, list):
                tender_okpd = {str(c)[:2] for c in codes}
            elif isinstance(codes, dict):
                tender_okpd = {str(k)[:2] for k in codes}

        company_okpd = set()
        if company.get("okpd2_codes"):
            codes = company["okpd2_codes"]
            if isinstance(codes, list):
                company_okpd = {str(c)[:2] for c in codes}
            elif isinstance(codes, dict):
                company_okpd = {str(k)[:2] for k in codes}

        similar_count = 0
        for contract in (past_contracts if isinstance(past_contracts, list) else []):
            contract_subject = str(contract.get("subject", "")).lower()
            if any(d in contract_subject for d in tender_okpd):
                similar_count += 1

        okpd_overlap = len(tender_okpd & company_okpd) / max(len(tender_okpd), 1)

        missing = analysis.get("missing_requirements") or []
        mandatory_missing = sum(
            1 for r in missing if r.get("is_mandatory") if isinstance(r, dict)
        )

        risk_flags = analysis.get("risk_flags") or []
        high_risks = sum(
            1 for r in risk_flags if r.get("level") == "HIGH" if isinstance(r, dict)
        )

        is_smp_match = 0.0
        if company.get("smp_status"):
            tender_text = (tender.get("full_text") or "").lower()
            if "субъект мсп" in tender_text or "субъект сп" in tender_text:
                is_smp_match = 1.0

        features = np.array([
            overall,
            qual,
            fin,
            tech,
            doc_score,
            min(budget_ratio, 5.0),
            min(experience_years / 20.0, 1.0),
            min(past_count / 30.0, 1.0),
            min(similar_count / 10.0, 1.0),
            okpd_overlap,
            min(mandatory_missing / 5.0, 1.0),
            min(high_risks / 5.0, 1.0),
            is_smp_match,
        ], dtype=np.float32)
        return features

    def predict(
        self,
        analysis: Dict[str, Any],
        tender: Dict[str, Any],
        company: Dict[str, Any],
    ) -> float:
        if not self._trained or self._pipeline is None:
            return self._heuristic(analysis)
        try:
            features = self.get_features(analysis, tender, company).reshape(1, -1)
            prob = self._pipeline.predict_proba(features)[0][1]
            return float(np.clip(prob, 0.01, 0.99))
        except Exception as e:
            logger.warning(f"Model predict failed: {e}; using heuristic")
            return self._heuristic(analysis)

    def _heuristic(self, analysis: Dict[str, Any]) -> float:
        score = float(analysis.get("overall_match_score") or 0.5)
        risk_flags = analysis.get("risk_flags") or []
        high_risks = sum(1 for r in risk_flags if r.get("level") == "HIGH")
        missing = analysis.get("missing_requirements") or []
        mandatory_missing = sum(1 for r in missing if r.get("is_mandatory"))
        prob = score * 0.7 - high_risks * 0.05 - mandatory_missing * 0.08
        return float(np.clip(prob, 0.01, 0.99))

    def train(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        if len(history) < 5:
            logger.warning("Not enough history to train (<5 records); using synthetic data")
            X, y = self._generate_synthetic_data(n=300)
        else:
            X_list, y_list = [], []
            for record in history:
                analysis = record.get("analysis") or {}
                tender = record.get("tender") or {}
                company = record.get("company") or {}
                won = record.get("won")
                if won is None:
                    continue
                features = self.get_features(analysis, tender, company)
                X_list.append(features)
                y_list.append(int(won))
            if not X_list:
                X, y = self._generate_synthetic_data(n=300)
            else:
                X = np.vstack(X_list)
                y = np.array(y_list)

        self._pipeline = _build_pipeline()
        self._pipeline.fit(X, y)
        self._trained = True
        self._save()

        from sklearn.model_selection import cross_val_score
        try:
            scores = cross_val_score(self._pipeline, X, y, cv=min(5, len(y)), scoring="accuracy")
            accuracy = float(np.mean(scores))
        except Exception:
            accuracy = 0.0

        logger.info(f"Model retrained. CV accuracy: {accuracy:.3f}")
        return {"trained": True, "cv_accuracy": accuracy, "n_samples": len(y)}

    def _generate_synthetic_data(self, n: int = 500):
        rng = np.random.default_rng(42)

        overall = rng.uniform(0, 1, n)
        qual = np.clip(overall + rng.normal(0, 0.1, n), 0, 1)
        fin = np.clip(overall + rng.normal(0, 0.1, n), 0, 1)
        tech = np.clip(overall + rng.normal(0, 0.1, n), 0, 1)
        doc_score = np.clip(overall + rng.normal(0, 0.1, n), 0, 1)
        budget_ratio = rng.uniform(0, 5, n)
        experience = rng.uniform(0, 1, n)
        past_count = rng.uniform(0, 1, n)
        similar_count = rng.uniform(0, 1, n)
        okpd_overlap = rng.uniform(0, 1, n)
        mandatory_missing = rng.uniform(0, 1, n)
        high_risks = rng.uniform(0, 1, n)
        is_smp_match = rng.integers(0, 2, n).astype(float)

        X = np.column_stack([
            overall, qual, fin, tech, doc_score,
            budget_ratio, experience, past_count, similar_count,
            okpd_overlap, mandatory_missing, high_risks, is_smp_match,
        ]).astype(np.float32)

        logit = (
            2.5 * overall
            + 0.5 * qual
            + 0.5 * fin
            + 0.5 * tech
            - 0.3 * budget_ratio
            + 0.4 * experience
            + 0.3 * past_count
            - 1.5 * mandatory_missing
            - 1.0 * high_risks
            + 0.2 * is_smp_match
            + rng.normal(0, 0.3, n)
            - 1.5
        )
        probs = 1 / (1 + np.exp(-logit))
        y = (rng.uniform(0, 1, n) < probs).astype(int)
        return X, y
