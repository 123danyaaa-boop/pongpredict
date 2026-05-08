import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.database import get_db
from core.models import TenderAnalysis, CompanyProfile, Tender, GeneratedDocument
from modules.doc_generator import DocumentGenerator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

_generator = DocumentGenerator()

DOC_TYPE_MAP = {
    "application": "APPLICATION",
    "declaration": "DECLARATION",
    "technical_proposal": "TECHNICAL_PROPOSAL",
    "form_2": "FORM_2",
    "full_package": "FULL_PACKAGE",
}


class GenerateRequest(BaseModel):
    tender_id: int
    company_id: int
    doc_types: List[str] = ["application", "declaration", "technical_proposal", "form_2"]


class DocumentOut(BaseModel):
    id: int
    analysis_id: int
    doc_type: str
    file_path: str

    class Config:
        from_attributes = True


@router.post("/generate", response_model=List[DocumentOut], status_code=201)
def generate_documents(
    payload: GenerateRequest,
    db: Session = Depends(get_db),
):
    tender = db.get(Tender, payload.tender_id)
    if not tender:
        raise HTTPException(404, "Тендер не найден")
    company = db.get(CompanyProfile, payload.company_id)
    if not company:
        raise HTTPException(404, "Компания не найдена")

    analysis = (
        db.query(TenderAnalysis)
        .filter(
            TenderAnalysis.tender_id == payload.tender_id,
            TenderAnalysis.company_id == payload.company_id,
        )
        .order_by(TenderAnalysis.created_at.desc())
        .first()
    )
    if not analysis:
        raise HTTPException(
            400, "Сначала выполните анализ тендера: POST /api/v1/tenders/{id}/analyze"
        )

    tender_dict = _tender_to_dict(tender)
    company_dict = _company_to_dict(company)
    analysis_dict = _analysis_to_dict(analysis)

    created_docs: List[GeneratedDocument] = []

    requested_types = [t.lower() for t in payload.doc_types]

    if "full_package" in requested_types:
        paths = _generator.generate_full_package(tender_dict, company_dict, analysis_dict)
        type_keys = ["APPLICATION", "DECLARATION", "TECHNICAL_PROPOSAL", "FORM_2"]
        for path, type_key in zip(paths, type_keys):
            doc = GeneratedDocument(
                analysis_id=analysis.id,
                doc_type=type_key,
                file_path=path,
            )
            db.add(doc)
            created_docs.append(doc)
    else:
        for type_name in requested_types:
            if type_name not in DOC_TYPE_MAP:
                continue
            try:
                if type_name == "application":
                    path = _generator.generate_application(tender_dict, company_dict, analysis_dict)
                elif type_name == "declaration":
                    path = _generator.generate_declaration(tender_dict, company_dict)
                elif type_name == "technical_proposal":
                    path = _generator.generate_technical_proposal(tender_dict, company_dict, analysis_dict)
                elif type_name == "form_2":
                    path = _generator.generate_form_2(tender_dict, company_dict)
                else:
                    continue
            except Exception as e:
                logger.error(f"Failed to generate {type_name}: {e}")
                continue

            doc = GeneratedDocument(
                analysis_id=analysis.id,
                doc_type=DOC_TYPE_MAP[type_name],
                file_path=path,
            )
            db.add(doc)
            created_docs.append(doc)

    tender.status = "DOCUMENTS_READY"
    db.commit()
    for doc in created_docs:
        db.refresh(doc)
    return created_docs


@router.get("/{doc_id}/download")
def download_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(GeneratedDocument, doc_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    path = Path(doc.file_path)
    if not path.exists():
        raise HTTPException(410, "Файл не найден на диске")
    return FileResponse(
        str(path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name,
    )


def _tender_to_dict(tender: Tender) -> dict:
    return {
        "id": tender.id,
        "title": tender.title,
        "external_id": tender.external_id,
        "customer_name": tender.customer_name,
        "initial_price": float(tender.initial_price) if tender.initial_price else None,
        "law_type": tender.law_type,
        "purchase_subject": tender.purchase_subject,
        "full_text": tender.full_text,
    }


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
        "staff_count": company.staff_count,
        "licenses": company.licenses,
        "smp_status": company.smp_status,
        "past_contracts": company.past_contracts,
        "authorized_person": company.authorized_person,
        "authorized_person_position": company.authorized_person_position,
        "bank_details": company.bank_details,
    }


def _analysis_to_dict(analysis: TenderAnalysis) -> dict:
    return {
        "id": analysis.id,
        "overall_match_score": analysis.overall_match_score,
        "qualification_score": analysis.qualification_score,
        "financial_score": analysis.financial_score,
        "technical_score": analysis.technical_score,
        "documentation_score": analysis.documentation_score,
        "win_probability": analysis.win_probability,
        "matched_requirements": analysis.matched_requirements or [],
        "missing_requirements": analysis.missing_requirements or [],
        "risk_flags": analysis.risk_flags or [],
        "recommendation": analysis.recommendation,
    }
