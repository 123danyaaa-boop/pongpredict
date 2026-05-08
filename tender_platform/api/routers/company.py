import logging
from typing import List, Optional, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.database import get_db
from core.models import CompanyProfile, ParticipationHistory, Tender

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/company", tags=["company"])


class CompanyCreate(BaseModel):
    name: str
    inn: str
    ogrn: Optional[str] = None
    legal_address: Optional[str] = None
    okpd2_codes: Optional[Any] = None
    founding_year: Optional[int] = None
    annual_revenue: Optional[float] = None
    annual_revenue_prev: Optional[float] = None
    staff_count: Optional[int] = None
    licenses: Optional[Any] = None
    smp_status: bool = False
    past_contracts: Optional[Any] = None
    authorized_person: Optional[str] = None
    authorized_person_position: Optional[str] = None
    bank_details: Optional[Any] = None


class CompanyOut(BaseModel):
    id: int
    name: str
    inn: str
    ogrn: Optional[str]
    legal_address: Optional[str]
    okpd2_codes: Optional[Any]
    founding_year: Optional[int]
    annual_revenue: Optional[float]
    staff_count: Optional[int]
    licenses: Optional[Any]
    smp_status: bool
    past_contracts: Optional[Any]
    authorized_person: Optional[str]
    authorized_person_position: Optional[str]
    bank_details: Optional[Any]

    class Config:
        from_attributes = True


class HistoryCreate(BaseModel):
    tender_id: int
    submitted_at: Optional[datetime] = None
    won: Optional[bool] = None
    rejection_reason: Optional[str] = None


class HistoryOut(BaseModel):
    id: int
    company_id: int
    tender_id: int
    submitted_at: Optional[datetime]
    won: Optional[bool]
    rejection_reason: Optional[str]

    class Config:
        from_attributes = True


@router.post("/", response_model=CompanyOut, status_code=201)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    company = CompanyProfile(**payload.model_dump())
    db.add(company)
    db.commit()
    db.refresh(company)
    logger.info(f"Company created: id={company.id} name={company.name}")
    return company


@router.get("/", response_model=List[CompanyOut])
def list_companies(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    return db.query(CompanyProfile).offset(skip).limit(limit).all()


@router.get("/{company_id}", response_model=CompanyOut)
def get_company(company_id: int, db: Session = Depends(get_db)):
    company = db.get(CompanyProfile, company_id)
    if not company:
        raise HTTPException(404, "Компания не найдена")
    return company


@router.put("/{company_id}", response_model=CompanyOut)
def update_company(
    company_id: int,
    payload: CompanyCreate,
    db: Session = Depends(get_db),
):
    company = db.get(CompanyProfile, company_id)
    if not company:
        raise HTTPException(404, "Компания не найдена")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(company, k, v)
    db.commit()
    db.refresh(company)
    return company


@router.post("/{company_id}/history", response_model=HistoryOut, status_code=201)
def add_history(
    company_id: int,
    payload: HistoryCreate,
    db: Session = Depends(get_db),
):
    if not db.get(CompanyProfile, company_id):
        raise HTTPException(404, "Компания не найдена")
    if not db.get(Tender, payload.tender_id):
        raise HTTPException(404, "Тендер не найден")
    record = ParticipationHistory(
        company_id=company_id,
        **payload.model_dump(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/{company_id}/history", response_model=List[HistoryOut])
def get_history(company_id: int, db: Session = Depends(get_db)):
    if not db.get(CompanyProfile, company_id):
        raise HTTPException(404, "Компания не найдена")
    return (
        db.query(ParticipationHistory)
        .filter(ParticipationHistory.company_id == company_id)
        .all()
    )
