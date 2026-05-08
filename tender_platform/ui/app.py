import sys
import json
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd

from core.database import create_tables, SessionLocal
from core.models import (
    Tender, TenderRequirement, CompanyProfile,
    TenderAnalysis, GeneratedDocument, ParticipationHistory,
)
from modules.document_parser import DocumentParser
from modules.requirement_matcher import RequirementMatcher
from modules.risk_analyzer import RiskAnalyzer
from modules.doc_generator import DocumentGenerator
from modules.win_probability_model import WinProbabilityModel

logging.basicConfig(level=logging.INFO)

# ──────────────────────────────────────────────
# Resource caching (models loaded once per session)
# ──────────────────────────────────────────────

@st.cache_resource
def get_parser():
    return DocumentParser()


@st.cache_resource
def get_matcher():
    return RequirementMatcher()


@st.cache_resource
def get_risk_analyzer():
    return RiskAnalyzer()


@st.cache_resource
def get_doc_generator():
    return DocumentGenerator()


@st.cache_resource
def get_win_model():
    return WinProbabilityModel()


# ──────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────

def get_db():
    return SessionLocal()


def _company_to_dict(c: CompanyProfile) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "inn": c.inn,
        "ogrn": c.ogrn,
        "legal_address": c.legal_address,
        "okpd2_codes": c.okpd2_codes,
        "founding_year": c.founding_year,
        "annual_revenue": float(c.annual_revenue) if c.annual_revenue else None,
        "annual_revenue_prev": float(c.annual_revenue_prev) if c.annual_revenue_prev else None,
        "staff_count": c.staff_count,
        "licenses": c.licenses,
        "smp_status": c.smp_status,
        "past_contracts": c.past_contracts,
        "authorized_person": c.authorized_person,
        "authorized_person_position": c.authorized_person_position,
        "bank_details": c.bank_details,
    }


def _tender_to_dict(t: Tender) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "external_id": t.external_id,
        "customer_name": t.customer_name,
        "initial_price": float(t.initial_price) if t.initial_price else None,
        "law_type": t.law_type,
        "purchase_subject": t.purchase_subject,
        "full_text": t.full_text,
        "okpd2_codes": t.okpd2_codes,
    }


def _analysis_to_dict(a: TenderAnalysis) -> dict:
    return {
        "id": a.id,
        "overall_match_score": a.overall_match_score,
        "qualification_score": a.qualification_score,
        "financial_score": a.financial_score,
        "technical_score": a.technical_score,
        "documentation_score": a.documentation_score,
        "win_probability": a.win_probability,
        "matched_requirements": a.matched_requirements or [],
        "missing_requirements": a.missing_requirements or [],
        "risk_flags": a.risk_flags or [],
        "recommendation": a.recommendation,
        "analysis_notes": a.analysis_notes,
    }


# ──────────────────────────────────────────────
# App entry point
# ──────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="TenderPlatform — Автоматизация закупок",
        page_icon="📋",
        layout="wide",
    )

    create_tables()

    st.title("📋 TenderPlatform — Интеллектуальная платформа закупок")
    st.caption("Автоматизация участия в государственных закупках (44-ФЗ, 223-ФЗ)")

    tab_upload, tab_company, tab_analysis, tab_docs, tab_history = st.tabs([
        "📂 Загрузка тендера",
        "🏢 Профиль компании",
        "🔍 Анализ соответствия",
        "📄 Генерация документов",
        "📊 История и аналитика",
    ])

    with tab_upload:
        _tab_upload()
    with tab_company:
        _tab_company()
    with tab_analysis:
        _tab_analysis()
    with tab_docs:
        _tab_documents()
    with tab_history:
        _tab_history()


# ══════════════════════════════════════════════
# TAB 1 — Upload tender
# ══════════════════════════════════════════════

def _tab_upload():
    st.header("Загрузка тендерной документации")
    st.info(
        "Загрузите PDF или DOCX-файл тендерной документации. "
        "Система автоматически извлечёт требования и метаданные."
    )

    with st.form("upload_form"):
        uploaded = st.file_uploader(
            "Файл тендерной документации (PDF / DOCX)",
            type=["pdf", "docx", "doc", "txt"],
        )
        title_input = st.text_input("Название тендера (необязательно — заполнится из документа)")
        submit = st.form_submit_button("Загрузить и разобрать")

    if submit and uploaded:
        suffix = Path(uploaded.name).suffix.lower()
        upload_dir = Path(__file__).resolve().parent.parent / "output" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        save_path = upload_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded.name}"
        with open(save_path, "wb") as f:
            shutil.copyfileobj(uploaded, f)

        parser = get_parser()
        progress = st.progress(0, text="Парсинг документа...")

        try:
            parsed = parser.parse_file(str(save_path))
            progress.progress(30, text="Извлечение метаданных...")
            metadata = parser.extract_metadata(parsed["full_text"])
            progress.progress(60, text="Извлечение требований...")
            req_dicts = parser.extract_requirements(parsed)
            progress.progress(90, text="Сохранение в базу данных...")

            db = get_db()
            try:
                tender = Tender(
                    title=title_input or uploaded.name,
                    source_file_path=str(save_path),
                    full_text=parsed.get("full_text", ""),
                    status="ANALYZED",
                    external_id=metadata.get("external_id"),
                    customer_inn=metadata.get("customer_inn"),
                    initial_price=metadata.get("initial_price"),
                    law_type=metadata.get("law_type", "FZ_44"),
                )
                db.add(tender)
                db.flush()

                for rd in req_dicts:
                    req = TenderRequirement(
                        tender_id=tender.id,
                        category=rd["category"],
                        text=rd["text"],
                        is_mandatory=rd["is_mandatory"],
                        source_page=rd.get("source_page"),
                        extracted_value=rd.get("extracted_value"),
                        risk_level=rd.get("risk_level", "LOW"),
                    )
                    db.add(req)
                db.commit()
                progress.progress(100, text="Готово!")

                st.success(f"Тендер #{tender.id} успешно загружен!")

                # Show metadata
                col1, col2, col3 = st.columns(3)
                with col1:
                    price = metadata.get("initial_price")
                    st.metric("НМЦК", f"{price:,.0f} ₽" if price else "Не извлечено")
                with col2:
                    st.metric("Закон", metadata.get("law_type", "Не определён"))
                with col3:
                    st.metric("Требований", len(req_dicts))

                if req_dicts:
                    st.subheader("Извлечённые требования")
                    df = pd.DataFrame([
                        {
                            "Категория": r["category"],
                            "Требование": r["text"][:120] + ("…" if len(r["text"]) > 120 else ""),
                            "Обязательное": "✅" if r["is_mandatory"] else "—",
                            "Риск": r.get("risk_level", "LOW"),
                            "Стр.": r.get("source_page", ""),
                        }
                        for r in req_dicts
                    ])

                    def _risk_color(val):
                        colors = {"HIGH": "background-color: #ffcccc",
                                  "MEDIUM": "background-color: #fff3cc",
                                  "LOW": "background-color: #ccffcc"}
                        return colors.get(val, "")

                    st.dataframe(
                        df.style.applymap(_risk_color, subset=["Риск"]),
                        use_container_width=True,
                    )
            finally:
                db.close()
        except Exception as e:
            st.error(f"Ошибка при обработке: {e}")
            progress.empty()

    st.divider()
    st.subheader("Загруженные тендеры")
    db = get_db()
    try:
        tenders = db.query(Tender).order_by(Tender.created_at.desc()).limit(20).all()
        if tenders:
            df = pd.DataFrame([
                {
                    "ID": t.id,
                    "Название": t.title[:60],
                    "НМЦК": f"{float(t.initial_price):,.0f} ₽" if t.initial_price else "—",
                    "Закон": t.law_type or "—",
                    "Статус": t.status,
                    "Создан": t.created_at.strftime("%d.%m.%Y"),
                }
                for t in tenders
            ])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Тендеры ещё не загружены.")
    finally:
        db.close()


# ══════════════════════════════════════════════
# TAB 2 — Company profile
# ══════════════════════════════════════════════

def _tab_company():
    st.header("Профиль компании-участника")

    db = get_db()
    try:
        companies = db.query(CompanyProfile).all()
    finally:
        db.close()

    company_names = {c.id: f"[{c.id}] {c.name}" for c in companies}

    mode = st.radio("Режим", ["Создать новую", "Редактировать существующую"], horizontal=True)

    selected_company: Optional[CompanyProfile] = None
    if mode == "Редактировать существующую" and companies:
        sel_id = st.selectbox("Компания", list(company_names.keys()), format_func=lambda i: company_names[i])
        db2 = get_db()
        try:
            selected_company = db2.get(CompanyProfile, sel_id)
        finally:
            db2.close()

    def _val(field, default=""):
        if selected_company:
            v = getattr(selected_company, field, default)
            return v if v is not None else default
        return default

    with st.form("company_form"):
        st.subheader("Основные данные")
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Полное наименование *", value=str(_val("name")))
            inn = st.text_input("ИНН *", value=str(_val("inn")))
            ogrn = st.text_input("ОГРН", value=str(_val("ogrn")))
        with col2:
            legal_address = st.text_input("Юридический адрес", value=str(_val("legal_address")))
            founding_year = st.number_input(
                "Год основания", min_value=1900, max_value=datetime.now().year,
                value=int(_val("founding_year") or 2015),
            )
            staff_count = st.number_input(
                "Среднесписочная численность", min_value=1, max_value=100000,
                value=int(_val("staff_count") or 10),
            )

        st.subheader("Финансы")
        col3, col4 = st.columns(2)
        with col3:
            annual_revenue = st.number_input(
                "Годовая выручка (руб.)", min_value=0.0, step=100000.0,
                value=float(_val("annual_revenue") or 0.0),
            )
        with col4:
            annual_revenue_prev = st.number_input(
                "Выручка предыдущего года (руб.)", min_value=0.0, step=100000.0,
                value=float(_val("annual_revenue_prev") or 0.0),
            )

        smp_status = st.checkbox(
            "Субъект малого предпринимательства (СМП/МСП)",
            value=bool(_val("smp_status", False)),
        )

        st.subheader("Коды ОКПД2")
        okpd2_raw = st.text_area(
            "Коды ОКПД2 (через запятую, напр.: 62.01, 63.11)",
            value=", ".join(_val("okpd2_codes") or []) if isinstance(_val("okpd2_codes"), list) else "",
        )

        st.subheader("Лицензии и сертификаты")
        licenses_raw = st.text_area(
            "Лицензии (по одной на строку)",
            value="\n".join(
                (lic.get("name", lic) if isinstance(lic, dict) else str(lic))
                for lic in (_val("licenses") or [])
            ) if isinstance(_val("licenses"), list) else "",
        )

        st.subheader("Подписант")
        col5, col6 = st.columns(2)
        with col5:
            authorized_person = st.text_input(
                "ФИО подписанта", value=str(_val("authorized_person"))
            )
        with col6:
            authorized_person_position = st.text_input(
                "Должность", value=str(_val("authorized_person_position"))
            )

        st.subheader("Банковские реквизиты")
        col7, col8, col9 = st.columns(3)
        existing_bd = _val("bank_details") or {}
        if not isinstance(existing_bd, dict):
            existing_bd = {}
        with col7:
            bank_name = st.text_input("Банк", value=existing_bd.get("bank_name", ""))
        with col8:
            bank_account = st.text_input("Расчётный счёт", value=existing_bd.get("account", ""))
        with col9:
            bank_bik = st.text_input("БИК", value=existing_bd.get("bik", ""))

        st.subheader("История контрактов")
        past_raw = st.text_area(
            "Прошлые контракты (JSON-список или пустое поле)",
            value=json.dumps(_val("past_contracts") or [], ensure_ascii=False, indent=2),
            height=150,
        )

        save_btn = st.form_submit_button("💾 Сохранить профиль")

    if save_btn:
        if not name or not inn:
            st.error("Заполните обязательные поля: Наименование и ИНН")
            return

        okpd2_list = [c.strip() for c in okpd2_raw.split(",") if c.strip()]
        licenses_list = [{"name": l.strip()} for l in licenses_raw.splitlines() if l.strip()]

        try:
            past_contracts = json.loads(past_raw) if past_raw.strip() else []
        except json.JSONDecodeError:
            st.error("Ошибка формата JSON в поле «Прошлые контракты»")
            return

        data = dict(
            name=name, inn=inn, ogrn=ogrn or None,
            legal_address=legal_address or None,
            okpd2_codes=okpd2_list,
            founding_year=int(founding_year),
            annual_revenue=annual_revenue if annual_revenue else None,
            annual_revenue_prev=annual_revenue_prev if annual_revenue_prev else None,
            staff_count=int(staff_count),
            licenses=licenses_list,
            smp_status=smp_status,
            past_contracts=past_contracts,
            authorized_person=authorized_person or None,
            authorized_person_position=authorized_person_position or None,
            bank_details={"bank_name": bank_name, "account": bank_account, "bik": bank_bik},
        )

        db = get_db()
        try:
            if mode == "Редактировать существующую" and selected_company:
                company_obj = db.get(CompanyProfile, selected_company.id)
                for k, v in data.items():
                    setattr(company_obj, k, v)
                db.commit()
                st.success(f"Профиль компании #{selected_company.id} обновлён!")
            else:
                company_obj = CompanyProfile(**data)
                db.add(company_obj)
                db.commit()
                st.success(f"Компания #{company_obj.id} создана!")
        finally:
            db.close()

    # History section
    st.divider()
    st.subheader("История участия в тендерах")
    if companies:
        db = get_db()
        try:
            hist_company_id = st.selectbox(
                "Компания (история)", list(company_names.keys()),
                format_func=lambda i: company_names[i],
                key="history_company_select",
            )
            history = (
                db.query(ParticipationHistory)
                .filter(ParticipationHistory.company_id == hist_company_id)
                .all()
            )
            if history:
                df = pd.DataFrame([
                    {
                        "ID": h.id,
                        "Тендер ID": h.tender_id,
                        "Дата подачи": h.submitted_at.strftime("%d.%m.%Y") if h.submitted_at else "—",
                        "Результат": "✅ Победа" if h.won else ("❌ Отказ" if h.won is False else "🕐 Ожидание"),
                        "Причина отказа": (h.rejection_reason or "")[:60],
                    }
                    for h in history
                ])
                st.dataframe(df, use_container_width=True)
            else:
                st.info("История участия пуста.")

            with st.expander("Добавить запись в историю"):
                tenders_db = db.query(Tender).limit(50).all()
                if tenders_db:
                    tid = st.selectbox(
                        "Тендер", [t.id for t in tenders_db],
                        format_func=lambda i: f"[{i}] {next((t.title[:40] for t in tenders_db if t.id == i), '')}",
                        key="add_hist_tender",
                    )
                    won_val = st.selectbox("Результат", ["Победа", "Отказ", "Ожидание"])
                    rejection = st.text_input("Причина отказа (если отказ)")
                    if st.button("Добавить"):
                        won_bool = {"Победа": True, "Отказ": False, "Ожидание": None}[won_val]
                        record = ParticipationHistory(
                            company_id=hist_company_id,
                            tender_id=tid,
                            submitted_at=datetime.now(),
                            won=won_bool,
                            rejection_reason=rejection or None,
                        )
                        db.add(record)
                        db.commit()
                        st.success("Запись добавлена!")
                        st.rerun()
        finally:
            db.close()

    st.divider()
    if st.button("🤖 Обучить модель вероятности победы на истории"):
        db = get_db()
        try:
            history_records = db.query(ParticipationHistory).filter(
                ParticipationHistory.won.isnot(None)
            ).all()
            win_model = get_win_model()
            history_dicts = [
                {
                    "won": h.won,
                    "analysis": {},
                    "tender": {},
                    "company": {},
                }
                for h in history_records
            ]
            result = win_model.train(history_dicts)
            st.success(
                f"Модель обучена на {result['n_samples']} примерах. "
                f"CV Accuracy: {result.get('cv_accuracy', 0):.1%}"
            )
        finally:
            db.close()


# ══════════════════════════════════════════════
# TAB 3 — Analysis
# ══════════════════════════════════════════════

def _tab_analysis():
    st.header("Анализ соответствия тендеру")

    db = get_db()
    try:
        tenders = db.query(Tender).order_by(Tender.created_at.desc()).all()
        companies = db.query(CompanyProfile).all()
    finally:
        db.close()

    if not tenders:
        st.warning("Нет загруженных тендеров. Перейдите на вкладку «Загрузка тендера».")
        return
    if not companies:
        st.warning("Нет профилей компаний. Перейдите на вкладку «Профиль компании».")
        return

    col1, col2 = st.columns(2)
    with col1:
        tender_id = st.selectbox(
            "Тендер",
            [t.id for t in tenders],
            format_func=lambda i: f"[{i}] {next((t.title[:50] for t in tenders if t.id == i), '')}",
        )
    with col2:
        company_id = st.selectbox(
            "Компания",
            [c.id for c in companies],
            format_func=lambda i: f"[{i}] {next((c.name for c in companies if c.id == i), '')}",
        )

    if st.button("🚀 Запустить анализ", type="primary"):
        db = get_db()
        try:
            tender_obj = db.get(Tender, tender_id)
            company_obj = db.get(CompanyProfile, company_id)

            if not tender_obj or not company_obj:
                st.error("Тендер или компания не найдены")
                return

            parser = get_parser()
            matcher = get_matcher()
            risk_an = get_risk_analyzer()
            win_model = get_win_model()

            progress = st.progress(0, text="Подготовка документа...")

            full_text = tender_obj.full_text or ""
            pages = [{"number": 1, "text": full_text}]
            if not full_text and tender_obj.source_file_path:
                parsed = parser.parse_file(tender_obj.source_file_path)
                full_text = parsed["full_text"]
                pages = parsed["pages"]
                tender_obj.full_text = full_text
                db.commit()

            progress.progress(25, text="Извлечение требований...")
            parsed_doc = {"full_text": full_text, "pages": pages}
            req_dicts = parser.extract_requirements(parsed_doc)

            db.query(TenderRequirement).filter(
                TenderRequirement.tender_id == tender_id
            ).delete()
            for rd in req_dicts:
                db.add(TenderRequirement(
                    tender_id=tender_id,
                    category=rd["category"],
                    text=rd["text"],
                    is_mandatory=rd["is_mandatory"],
                    source_page=rd.get("source_page"),
                    extracted_value=rd.get("extracted_value"),
                    risk_level=rd.get("risk_level", "LOW"),
                ))
            db.flush()

            progress.progress(50, text="Сопоставление с профилем компании...")
            company_dict = _company_to_dict(company_obj)
            match_result = matcher.match(req_dicts, company_dict)

            progress.progress(70, text="Анализ рисков...")
            risk_flags = risk_an.analyze(full_text, req_dicts, pages)
            match_result["risk_flags"] = risk_flags

            progress.progress(85, text="Расчёт вероятности победы...")
            tender_dict = _tender_to_dict(tender_obj)
            win_prob = win_model.predict(match_result, tender_dict, company_dict)
            match_result["win_probability"] = win_prob

            progress.progress(95, text="Сохранение результатов...")
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
            tender_obj.status = "ANALYZED"
            db.commit()
            progress.progress(100, text="Анализ завершён!")

            st.session_state["last_analysis"] = _analysis_to_dict(analysis)
            st.session_state["last_analysis_id"] = analysis.id
        finally:
            db.close()

    # Show results
    result = st.session_state.get("last_analysis")
    if result:
        _show_analysis_results(result)


def _show_analysis_results(result: dict):
    rec = result.get("recommendation", "CONSIDER")
    rec_colors = {
        "PARTICIPATE": ("#d4edda", "#155724", "✅ УЧАСТВОВАТЬ"),
        "CONSIDER": ("#fff3cd", "#856404", "⚠️ РАССМОТРЕТЬ"),
        "AVOID": ("#f8d7da", "#721c24", "❌ ОТКАЗАТЬСЯ"),
    }
    bg, fg, label = rec_colors.get(rec, ("#e9ecef", "#343a40", "❓ НЕТ ДАННЫХ"))

    st.markdown(
        f"""<div style="background:{bg};color:{fg};padding:20px;border-radius:10px;
        text-align:center;font-size:24px;font-weight:bold;margin:10px 0">{label}</div>""",
        unsafe_allow_html=True,
    )

    win_prob = result.get("win_probability") or 0.0
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Вероятность победы", f"{win_prob:.1%}")
        st.metric("Общий балл соответствия", f"{result.get('overall_match_score', 0):.1%}")
    with col2:
        st.metric(
            "Выполненных требований",
            len(result.get("matched_requirements") or []),
        )
        st.metric(
            "Невыполненных требований",
            len(result.get("missing_requirements") or []),
        )

    st.subheader("Соответствие по категориям")
    categories = {
        "Квалификация": result.get("qualification_score") or 0,
        "Финансы": result.get("financial_score") or 0,
        "Технические": result.get("technical_score") or 0,
        "Документация": result.get("documentation_score") or 0,
    }
    for cat, score in categories.items():
        st.progress(float(score), text=f"{cat}: {score:.0%}")

    if result.get("analysis_notes"):
        st.info(result["analysis_notes"])

    col_match, col_miss = st.columns(2)
    with col_match:
        st.subheader("✅ Выполненные требования")
        matched = result.get("matched_requirements") or []
        for r in matched[:20]:
            st.markdown(f"- {r['text'][:120]}")

    with col_miss:
        st.subheader("❌ Невыполненные требования")
        missing = result.get("missing_requirements") or []
        for r in missing[:20]:
            color = "🔴" if r.get("is_mandatory") else "🟡"
            st.markdown(f"{color} {r['text'][:120]}")

    risk_flags = result.get("risk_flags") or []
    if risk_flags:
        st.subheader("⚠️ Выявленные риски")
        risk_color_map = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
        df_risks = pd.DataFrame([
            {
                "Уровень": f"{risk_color_map.get(r['level'], '⚪')} {r['level']}",
                "Описание": r["description"],
                "Источник": r.get("source_text", "")[:80],
                "Стр.": r.get("page", ""),
            }
            for r in risk_flags
        ])
        st.dataframe(df_risks, use_container_width=True)


# ══════════════════════════════════════════════
# TAB 4 — Document generation
# ══════════════════════════════════════════════

def _tab_documents():
    st.header("Генерация пакета документов")

    db = get_db()
    try:
        tenders = db.query(Tender).order_by(Tender.created_at.desc()).all()
        companies = db.query(CompanyProfile).all()
    finally:
        db.close()

    if not tenders or not companies:
        st.warning("Для генерации документов нужны тендер и профиль компании.")
        return

    col1, col2 = st.columns(2)
    with col1:
        tender_id = st.selectbox(
            "Тендер",
            [t.id for t in tenders],
            format_func=lambda i: f"[{i}] {next((t.title[:50] for t in tenders if t.id == i), '')}",
            key="doc_tender",
        )
    with col2:
        company_id = st.selectbox(
            "Компания",
            [c.id for c in companies],
            format_func=lambda i: f"[{i}] {next((c.name for c in companies if c.id == i), '')}",
            key="doc_company",
        )

    st.subheader("Документы для генерации")
    col_a, col_b, col_c, col_d = st.columns(4)
    gen_application = col_a.checkbox("📝 Заявка", value=True)
    gen_declaration = col_b.checkbox("📋 Декларация", value=True)
    gen_tech = col_c.checkbox("🔧 Техническое предложение", value=True)
    gen_form2 = col_d.checkbox("📊 Форма 2", value=True)

    if st.button("📦 Сформировать комплект документов", type="primary"):
        selected_types = []
        if gen_application:
            selected_types.append("application")
        if gen_declaration:
            selected_types.append("declaration")
        if gen_tech:
            selected_types.append("technical_proposal")
        if gen_form2:
            selected_types.append("form_2")

        if not selected_types:
            st.error("Выберите хотя бы один тип документа.")
            return

        db = get_db()
        try:
            tender_obj = db.get(Tender, tender_id)
            company_obj = db.get(CompanyProfile, company_id)

            analysis_obj = (
                db.query(TenderAnalysis)
                .filter(
                    TenderAnalysis.tender_id == tender_id,
                    TenderAnalysis.company_id == company_id,
                )
                .order_by(TenderAnalysis.created_at.desc())
                .first()
            )
            if not analysis_obj:
                st.warning(
                    "Для генерации документов сначала выполните анализ на вкладке «Анализ соответствия»."
                )
                return

            tender_dict = _tender_to_dict(tender_obj)
            company_dict = _company_to_dict(company_obj)
            analysis_dict = _analysis_to_dict(analysis_obj)
            gen = get_doc_generator()

            generated_paths = []
            progress = st.progress(0, text="Генерация документов...")
            step = 100 // max(len(selected_types), 1)
            current = 0

            DOC_TYPE_MAP = {
                "application": ("APPLICATION", gen.generate_application),
                "declaration": ("DECLARATION", lambda t, c, a: gen.generate_declaration(t, c)),
                "technical_proposal": ("TECHNICAL_PROPOSAL", gen.generate_technical_proposal),
                "form_2": ("FORM_2", lambda t, c, a: gen.generate_form_2(t, c)),
            }

            for type_name in selected_types:
                type_key, gen_fn = DOC_TYPE_MAP[type_name]
                path = gen_fn(tender_dict, company_dict, analysis_dict)
                doc = GeneratedDocument(
                    analysis_id=analysis_obj.id,
                    doc_type=type_key,
                    file_path=path,
                )
                db.add(doc)
                generated_paths.append((type_key, path, doc))
                current += step
                progress.progress(min(current, 100), text=f"Сгенерирован: {type_name}")

            tender_obj.status = "DOCUMENTS_READY"
            db.commit()
            for _, _, doc in generated_paths:
                db.refresh(doc)

            progress.progress(100, text="Готово!")
            st.success(f"Сгенерировано {len(generated_paths)} документов!")

            st.subheader("Скачать документы")
            type_labels = {
                "APPLICATION": "📝 Заявка",
                "DECLARATION": "📋 Декларация",
                "TECHNICAL_PROPOSAL": "🔧 Техническое предложение",
                "FORM_2": "📊 Форма 2",
            }
            for type_key, path, doc in generated_paths:
                path_obj = Path(path)
                if path_obj.exists():
                    with open(path, "rb") as f:
                        file_bytes = f.read()
                    st.download_button(
                        label=f"⬇️ Скачать: {type_labels.get(type_key, type_key)}",
                        data=file_bytes,
                        file_name=path_obj.name,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"dl_{doc.id}",
                    )

                    with st.expander(f"Предпросмотр: {type_labels.get(type_key, type_key)}"):
                        try:
                            from docx import Document as DocxDoc
                            docx = DocxDoc(path)
                            preview = "\n".join(p.text for p in docx.paragraphs[:30] if p.text.strip())
                            st.text(preview[:2000])
                        except Exception:
                            st.info("Предпросмотр недоступен")
        finally:
            db.close()


# ══════════════════════════════════════════════
# TAB 5 — History & analytics
# ══════════════════════════════════════════════

def _tab_history():
    st.header("История анализов и аналитика")

    db = get_db()
    try:
        analyses = (
            db.query(TenderAnalysis)
            .order_by(TenderAnalysis.created_at.desc())
            .limit(100)
            .all()
        )
        tenders = {t.id: t for t in db.query(Tender).all()}
        companies = {c.id: c for c in db.query(CompanyProfile).all()}
        history = db.query(ParticipationHistory).all()
    finally:
        db.close()

    if analyses:
        st.subheader("Проведённые анализы")
        df = pd.DataFrame([
            {
                "ID": a.id,
                "Тендер": tenders.get(a.tender_id, type("", (), {"title": "—"})()).title[:40]
                if a.tender_id in tenders else "—",
                "Компания": companies.get(a.company_id, type("", (), {"name": "—"})()).name[:30]
                if a.company_id in companies else "—",
                "Балл соответствия": f"{a.overall_match_score:.1%}" if a.overall_match_score else "—",
                "Вер. победы": f"{a.win_probability:.1%}" if a.win_probability else "—",
                "Рекомендация": a.recommendation or "—",
                "Дата": a.created_at.strftime("%d.%m.%Y %H:%M"),
            }
            for a in analyses
        ])
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Анализы ещё не проводились.")

    # Win rate chart
    if history:
        st.subheader("Статистика участия")
        won_count = sum(1 for h in history if h.won is True)
        lost_count = sum(1 for h in history if h.won is False)
        pending_count = sum(1 for h in history if h.won is None)

        col1, col2, col3 = st.columns(3)
        col1.metric("Победы", won_count)
        col2.metric("Отказы", lost_count)
        col3.metric("В процессе", pending_count)

        if won_count + lost_count > 0:
            win_rate = won_count / (won_count + lost_count)
            st.metric("Процент побед", f"{win_rate:.1%}")

        # Top rejection reasons
        rejections = [h.rejection_reason for h in history if h.rejection_reason]
        if rejections:
            st.subheader("Топ причин отказов")
            from collections import Counter
            counts = Counter(rejections).most_common(3)
            for reason, count in counts:
                st.markdown(f"- **{reason}** — {count} раз(а)")

    # Score distribution
    if analyses:
        scores = [a.overall_match_score for a in analyses if a.overall_match_score is not None]
        if scores:
            st.subheader("Распределение баллов соответствия")
            import plotly.express as px
            fig = px.histogram(
                x=scores,
                nbins=20,
                labels={"x": "Балл соответствия"},
                title="Гистограмма баллов",
                color_discrete_sequence=["#636efa"],
            )
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        probs = [a.win_probability for a in analyses if a.win_probability is not None]
        if probs:
            st.subheader("Распределение вероятности победы")
            fig2 = px.histogram(
                x=probs,
                nbins=20,
                labels={"x": "Вероятность победы"},
                title="Гистограмма вероятностей",
                color_discrete_sequence=["#00cc96"],
            )
            fig2.update_layout(showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)


if __name__ == "__main__":
    main()
