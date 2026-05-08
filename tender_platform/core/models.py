import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Any
from sqlalchemy import (
    Integer, String, Text, DateTime, Boolean, Float,
    ForeignKey, JSON, Numeric,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class LawType(str, enum.Enum):
    FZ_44 = "FZ_44"
    FZ_223 = "FZ_223"


class TenderStatus(str, enum.Enum):
    NEW = "NEW"
    ANALYZED = "ANALYZED"
    MATCHED = "MATCHED"
    DOCUMENTS_READY = "DOCUMENTS_READY"
    ARCHIVED = "ARCHIVED"


class RequirementCategory(str, enum.Enum):
    QUALIFICATION = "QUALIFICATION"
    FINANCIAL = "FINANCIAL"
    TECHNICAL = "TECHNICAL"
    DOCUMENTATION = "DOCUMENTATION"
    RESTRICTION = "RESTRICTION"


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Recommendation(str, enum.Enum):
    PARTICIPATE = "PARTICIPATE"
    CONSIDER = "CONSIDER"
    AVOID = "AVOID"


class DocType(str, enum.Enum):
    APPLICATION = "APPLICATION"
    TECHNICAL_PROPOSAL = "TECHNICAL_PROPOSAL"
    DECLARATION = "DECLARATION"
    FORM_2 = "FORM_2"
    FULL_PACKAGE = "FULL_PACKAGE"


class Tender(Base):
    __tablename__ = "tenders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    customer_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    customer_inn: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    publication_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    submission_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    contract_execution_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    initial_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    purchase_subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    okpd2_codes: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    law_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    full_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="NEW")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    requirements: Mapped[List["TenderRequirement"]] = relationship(
        "TenderRequirement", back_populates="tender", cascade="all, delete-orphan"
    )
    analyses: Mapped[List["TenderAnalysis"]] = relationship(
        "TenderAnalysis", back_populates="tender", cascade="all, delete-orphan"
    )
    history: Mapped[List["ParticipationHistory"]] = relationship(
        "ParticipationHistory", back_populates="tender", cascade="all, delete-orphan"
    )


class TenderRequirement(Base):
    __tablename__ = "tender_requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tender_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenders.id"))
    category: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    source_page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    extracted_value: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(10), default="LOW")

    tender: Mapped["Tender"] = relationship("Tender", back_populates="requirements")


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    inn: Mapped[str] = mapped_column(String(20))
    ogrn: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    legal_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    okpd2_codes: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    founding_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    annual_revenue: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    annual_revenue_prev: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    staff_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    licenses: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    smp_status: Mapped[bool] = mapped_column(Boolean, default=False)
    past_contracts: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    authorized_person: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    authorized_person_position: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    bank_details: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

    analyses: Mapped[List["TenderAnalysis"]] = relationship(
        "TenderAnalysis", back_populates="company", cascade="all, delete-orphan"
    )
    history: Mapped[List["ParticipationHistory"]] = relationship(
        "ParticipationHistory", back_populates="company", cascade="all, delete-orphan"
    )


class TenderAnalysis(Base):
    __tablename__ = "tender_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tender_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenders.id"))
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("company_profiles.id"))
    overall_match_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qualification_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    financial_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    technical_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    documentation_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    win_probability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    matched_requirements: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    missing_requirements: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    risk_flags: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    recommendation: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    analysis_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tender: Mapped["Tender"] = relationship("Tender", back_populates="analyses")
    company: Mapped["CompanyProfile"] = relationship("CompanyProfile", back_populates="analyses")
    documents: Mapped[List["GeneratedDocument"]] = relationship(
        "GeneratedDocument", back_populates="analysis", cascade="all, delete-orphan"
    )


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    analysis_id: Mapped[int] = mapped_column(Integer, ForeignKey("tender_analyses.id"))
    doc_type: Mapped[str] = mapped_column(String(30))
    file_path: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    analysis: Mapped["TenderAnalysis"] = relationship("TenderAnalysis", back_populates="documents")


class ParticipationHistory(Base):
    __tablename__ = "participation_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("company_profiles.id"))
    tender_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenders.id"))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    won: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    company: Mapped["CompanyProfile"] = relationship("CompanyProfile", back_populates="history")
    tender: Mapped["Tender"] = relationship("Tender", back_populates="history")
