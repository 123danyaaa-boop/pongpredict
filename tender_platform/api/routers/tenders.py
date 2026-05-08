import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.database import get_db
from core.models import (
    Tender, TenderRequirement, TenderAnalysis, CompanyProfile, GeneratedDocument
)
from modules.document_parser import DocumentParser
from modules.requirement_matcher import RequirementMatcher
from modules.risk_analyzer import RiskAnalyzer
from modules.win_probability_model import WinProbabilityModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tenders", tags=["tenders"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "output" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_parser = DocumentParser()
_matcher = RequirementMatcher()
_risk_analyzer = RiskAnalyzer()
_win_model = WinProbabilityModel()


class TenderOut(BaseModel):
    id: int
    title: str
    external_id: Optional[str]
    customer_name: Optional[str]
    customer_inn: Optional[str]
    initial_price: Optional[float]
    law_type: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class AnalysisOut(BaseModel):
    id: int
    tender_id: int
    company_id: int
    overall_match_score: Optional[float]
    qualification_score: Optional[float]
    financial_score: Optional[float]
    technical_score: Optional[float]
    documentation_score: Optional[float]
    win_probability: Optional[float]
    recommendation: Optional[str]
    matched_requirements: Optional[list]
    missing_requirements: Optional[list]
    risk_flags: Optional[list]
    analysis_notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/upload", response_model=TenderOut, status_code=201)
async def upload_tender(
    file: UploadFile = File(...),
    title: str = Form(""),
    db: Session = Depends(get_db),
):
    suffix = Path(file.filename or "doc.pdf").suffix.lower()
    if suffix not in (".pdf", ".docx", ".doc", ".txt"):
        raise HTTPException(400, "Поддерживаются только PDF, DOCX, TXT")

    save_path = UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        parsed = _parser.parse_file(str(save_path))
        metadata = _parser.extract_metadata(parsed["full_text"])
    except Exception as e:
        logger.error(f"Parsing failed: {e}")
        parsed = {"full_text": "", "pages": []}
        metadata = {}

    tender = Tender(
        title=title or file.filename or "Без названия",
        source_file_path=str(save_path),
        full_text=parsed.get("full_text", ""),
        status="NEW",
        external_id=metadata.get("external_id"),
        customer_inn=metadata.get("customer_inn"),
        initial_price=metadata.get("initial_price"),
        law_type=metadata.get("law_type", "FZ_44"),
    )
    db.add(tender)
    db.commit()
    db.refresh(tender)
    logger.info(f"Tender uploaded: id={tender.id}")
    return tender


@router.get("/", response_model=List[TenderOut])
def list_tenders(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    return db.query(Tender).offset(skip).limit(limit).all()


@router.get("/{tender_id}", response_model=TenderOut)
def get_tender(tender_id: int, db: Session = Depends(get_db)):
    tender = db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(404, "Тендер не найден")
    return tender


@router.post("/{tender_id}/analyze", response_model=AnalysisOut)
def analyze_tender(
    tender_id: int,
    company_id: int,
    db: Session = Depends(get_db),
):
    tender = db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(404, "Тендер не найден")
    company = db.get(CompanyProfile, company_id)
    if not company:
        raise HTTPException(404, "Компания не найдена")

    # Step 1 — parse if needed
    if not tender.full_text and tender.source_file_path:
        parsed = _parser.parse_file(tender.source_file_path)
        tender.full_text = parsed["full_text"]
        pages = parsed.get("pages", [])
    else:
        pages = [{"number": 1, "text": tender.full_text or ""}]

    # Step 2 — extract requirements
    parsed_doc = {"full_text": tender.full_text or "", "pages": pages}
    req_dicts = _parser.extract_requirements(parsed_doc)

    # Persist requirements (replace old ones)
    db.query(TenderRequirement).filter(TenderRequirement.tender_id == tender_id).delete()
    req_objects = []
    for rd in req_dicts:
        req = TenderRequirement(
            tender_id=tender_id,
            category=rd["category"],
            text=rd["text"],
            is_mandatory=rd["is_mandatory"],
            source_page=rd.get("source_page"),
            extracted_value=rd.get("extracted_value"),
            risk_level=rd.get("risk_level", "LOW"),
        )
        db.add(req)
        req_objects.append(rd)
    db.flush()

    # Step 3 — match requirements
    company_dict = _company_to_dict(company)
    match_result = _matcher.match(req_objects, company_dict)

    # Step 4 — risk analysis
    risk_flags = _risk_analyzer.analyze(tender.full_text or "", req_objects, pages)
    match_result["risk_flags"] = risk_flags

    # Step 5 — win probability
    tender_dict = _tender_to_dict(tender)
    win_prob = _win_model.predict(match_result, tender_dict, company_dict)
    match_result["win_probability"] = win_prob

    # Step 6 — save analysis
    analysis = TenderAnalysis(
        tender_id=tender_id,
        company_id=company_id,
        overall_match_score=match_result.get("overall_match_score"),
        qualification_score=match_result.get("qualification_score"),
        financial_score=match_result.get("financial_score"),
        technical_score=match_result.get("technical_score"),
        documentation_score=match_result.get("documentation_score"),
        win_probability=win_prob,
        matched_requirements=match_result.get("matched_requirements"),
        missing_requirements=match_result.get("missing_requirements"),
        risk_flags=risk_flags,
        recommendation=match_result.get("recommendation"),
        analysis_notes=match_result.get("analysis_notes"),
    )
    db.add(analysis)
    tender.status = "ANALYZED"
    db.commit()
    db.refresh(analysis)
    logger.info(f"Analysis complete: tender_id={tender_id}, score={analysis.overall_match_score:.2f}")
    return analysis


@router.delete("/{tender_id}", status_code=204)
def delete_tender(tender_id: int, db: Session = Depends(get_db)):
    tender = db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(404, "Тендер не найден")
    db.delete(tender)
    db.commit()


def _company_to_dict(company: CompanyProfile) -> dict:
    return {
        "id": company.id,
        "name": company.name,
        "inn": company.inn,
        "ogrn": company.ogrn,
        "legal_address": company.legal_address,
        "okpd2_codes": company.okpd2_codes,
        "founding_year": company.founding_year,
        "annual_revenue": float(company.annual_revenue) if company.annual_revenue else None,
        "annual_revenue_prev": float(company.annual_revenue_prev) if company.annual_revenue_prev else None,
        "staff_count": company.staff_count,
        "licenses": company.licenses,
        "smp_status": company.smp_status,
        "past_contracts": company.past_contracts,
        "authorized_person": company.authorized_person,
        "authorized_person_position": company.authorized_person_position,
        "bank_details": company.bank_details,
    }


def _tender_to_dict(tender: Tender) -> dict:
    return {
        "id": tender.id,
        "title": tender.title,
        "external_id": tender.external_id,
        "customer_name": tender.customer_name,
        "customer_inn": tender.customer_inn,
        "initial_price": float(tender.initial_price) if tender.initial_price else None,
        "law_type": tender.law_type,
        "full_text": tender.full_text,
        "okpd2_codes": tender.okpd2_codes,
        "purchase_subject": tender.purchase_subject,
    }
