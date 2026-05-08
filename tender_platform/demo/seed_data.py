"""
Demo seed script -- creates 3 test tenders + 1 company profile and runs the full pipeline.
Run from the tender_platform/ directory:
    python demo/seed_data.py
"""

import sys
import io
import logging

# Ensure UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from datetime import datetime, timedelta

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import create_tables, SessionLocal
from core.models import (
    Tender, TenderRequirement, CompanyProfile, TenderAnalysis, ParticipationHistory
)
from modules.document_parser import DocumentParser
from modules.requirement_matcher import RequirementMatcher
from modules.risk_analyzer import RiskAnalyzer
from modules.doc_generator import DocumentGenerator
from modules.win_probability_model import WinProbabilityModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Synthetic tender texts
# ──────────────────────────────────────────────

TENDER_1_TEXT = """
ДОКУМЕНТАЦИЯ ОБ АУКЦИОНЕ В ЭЛЕКТРОННОЙ ФОРМЕ

Номер закупки: 0372200097524000001
Закупка осуществляется в соответствии с требованиями Федерального закона № 44-ФЗ.
Предмет закупки: Поставка медицинского оборудования (аппараты УЗИ экспертного класса).
Заказчик: ГБУЗ «Городская клиническая больница № 1»
ИНН заказчика: 7701234567

НАЧАЛЬНАЯ (МАКСИМАЛЬНАЯ) ЦЕНА КОНТРАКТА: 5 000 000 рублей.

Настоящая закупка проводится только для субъектов малого предпринимательства (МСП).
Участник должен являться субъектом малого предпринимательства или социально
ориентированной некоммерческой организацией (СОНКО).

ТРЕБОВАНИЯ К УЧАСТНИКАМ:
1. Участник обязан иметь опыт исполнения аналогичных контрактов не менее 3 лет.
2. Необходимо наличие лицензии на техническое обслуживание медицинской техники.
3. Участник должен подтвердить соответствие требованиям ГОСТ Р 50267.
4. Требуется подтверждение наличия квалифицированного персонала — не менее 5 специалистов
   с высшим медицинским или техническим образованием.
5. Финансовое обеспечение заявки — 2% от НМЦК (100 000 рублей).
6. Обеспечение исполнения контракта составляет 5% от НМЦК.
7. Национальный режим применяется в соответствии с Приказом Минфина.

ОТВЕТСТВЕННОСТЬ:
При нарушении сроков поставки штраф составляет 10% от стоимости контракта за каждый
день просрочки, но не более 30% от общей суммы контракта.
Предусмотрена неустойка за ненадлежащее исполнение обязательств.

Срок исполнения контракта: 30 дней с даты заключения контракта.
Авансирование не предусмотрено.
Срок подачи заявок: до 15.06.2025.
"""

TENDER_2_TEXT = """
ТЕХНИЧЕСКОЕ ЗАДАНИЕ
Закупка в соответствии с Федеральным законом № 44-ФЗ.

Предмет контракта: Оказание услуг технической поддержки серверной инфраструктуры.
Заказчик: Федеральное казённое учреждение «ЦОД Минфина»
ИНН заказчика: 7702345678
НМЦК: 2 500 000 рублей.

ОПИСАНИЕ УСЛУГ:
Исполнитель обязан обеспечить круглосуточную техническую поддержку серверной инфраструктуры,
включая администрирование серверов под управлением ОС Linux и Windows Server,
мониторинг доступности сервисов, устранение инцидентов.

ТРЕБОВАНИЯ К УЧАСТНИКАМ:
1. Участник должен иметь опыт исполнения аналогичных контрактов на оказание IT-услуг
   не менее 2 лет.
2. Необходимо наличие лицензии ФСТЭК России на деятельность по технической защите
   конфиденциальной информации.
3. Участник обязан иметь в штате не менее 3 сертифицированных специалистов.
4. Требуется подтверждение наличия сертификатов соответствия ISO 27001 или ГОСТ Р ИСО/МЭК 27001.

КОДЫ ОКПД2: 62.02.30 — Услуги по управлению компьютерными системами и сетями.

Обеспечение заявки: не требуется (НМЦК менее 5 млн руб.).
Гарантийный срок сопровождения: 12 месяцев.
Срок исполнения: 365 дней с даты подписания контракта.
Срок подачи заявок: до 20.06.2025.
"""

TENDER_3_TEXT = """
ДОКУМЕНТАЦИЯ О ПРОВЕДЕНИИ ОТКРЫТОГО КОНКУРСА

Закупка осуществляется в соответствии с Федеральным законом № 44-ФЗ.
Предмет закупки: Выполнение строительных работ по реконструкции административного здания.
НМЦК: 15 000 000 рублей.

Заказчик: Администрация Московского района
ИНН заказчика: 7709876543

КВАЛИФИКАЦИОННЫЕ ТРЕБОВАНИЯ:
1. Участник обязан являться членом саморегулируемой организации (СРО) в области
   строительства с допуском к работам, влияющим на безопасность объектов капитального
   строительства.
2. Опыт исполнения аналогичных строительных контрактов — не менее 5 лет.
3. Необходимо наличие строительной лицензии и свидетельства СРО.
4. Участник должен иметь годовую выручку не менее 10 000 000 рублей.
5. Среднесписочная численность работников — не менее 50 человек.

ФИНАНСОВЫЕ УСЛОВИЯ:
Обеспечение заявки: 1% от НМЦК = 150 000 рублей (банковская гарантия).
Обеспечение исполнения контракта: 10% от НМЦК = 1 500 000 рублей.
Банковская гарантия обязательна.
Авансирование предусмотрено в размере 30% после подписания контракта.

ОТВЕТСТВЕННОСТЬ:
Штраф за нарушение сроков: 1/300 ключевой ставки ЦБ РФ в день.
При расторжении по вине подрядчика неустойка составляет 10% от стоимости контракта.
Заказчик вправе расторгнуть контракт в одностороннем порядке при существенном нарушении.

Срок выполнения работ: 180 дней.
Страхование строительно-монтажных рисков — обязательно.
Срок подачи заявок: до 25.06.2025.
"""


def run_pipeline(
    db,
    tender: Tender,
    company: CompanyProfile,
    parser: DocumentParser,
    matcher: RequirementMatcher,
    risk_analyzer: RiskAnalyzer,
    doc_generator: DocumentGenerator,
    win_model: WinProbabilityModel,
) -> TenderAnalysis:
    logger.info(f"\n{'='*60}")
    logger.info(f"Обработка тендера: {tender.title}")
    logger.info(f"{'='*60}")

    # Step 1: parse
    parsed_doc = {"full_text": tender.full_text or "", "pages": [{"number": 1, "text": tender.full_text or ""}]}
    req_dicts = parser.extract_requirements(parsed_doc)
    logger.info(f"Извлечено требований: {len(req_dicts)}")

    # Save requirements
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
    db.flush()

    # Step 2: match
    company_dict = {
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
    match_result = matcher.match(req_dicts, company_dict)
    logger.info(f"Балл соответствия: {match_result['overall_match_score']:.1%}")
    logger.info(f"Рекомендация: {match_result['recommendation']}")

    # Step 3: risks
    risk_flags = risk_analyzer.analyze(tender.full_text or "", req_dicts)
    overall_risk = risk_analyzer.overall_risk_level(risk_flags)
    logger.info(f"Рисков найдено: {len(risk_flags)} (уровень: {overall_risk})")
    for rf in risk_flags[:5]:
        logger.info(f"  [{rf['level']}] {rf['description']}")

    match_result["risk_flags"] = risk_flags

    # Step 4: win probability
    tender_dict = {
        "id": tender.id,
        "title": tender.title,
        "initial_price": float(tender.initial_price) if tender.initial_price else None,
        "law_type": tender.law_type,
        "full_text": tender.full_text,
        "okpd2_codes": tender.okpd2_codes,
    }
    win_prob = win_model.predict(match_result, tender_dict, company_dict)
    logger.info(f"Вероятность победы: {win_prob:.1%}")

    # Step 5: save analysis
    analysis = TenderAnalysis(
        tender_id=tender.id,
        company_id=company.id,
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
    db.flush()

    # Step 6: generate documents
    analysis_dict = {
        "id": analysis.id,
        "overall_match_score": analysis.overall_match_score,
        "qualification_score": analysis.qualification_score,
        "financial_score": analysis.financial_score,
        "technical_score": analysis.technical_score,
        "documentation_score": analysis.documentation_score,
        "win_probability": analysis.win_probability,
        "matched_requirements": analysis.matched_requirements or [],
        "missing_requirements": analysis.missing_requirements or [],
        "risk_flags": risk_flags,
        "recommendation": analysis.recommendation,
    }
    try:
        paths = doc_generator.generate_full_package(tender_dict, company_dict, analysis_dict)
        logger.info(f"Сгенерировано документов: {len(paths)}")
        for p in paths:
            logger.info(f"  → {p}")
        tender.status = "DOCUMENTS_READY"
    except Exception as e:
        logger.warning(f"Генерация документов не выполнена: {e}")

    db.commit()
    db.refresh(analysis)

    # Print summary
    print(f"\n{'='*60}")
    print(f"  Тендер: {tender.title}")
    print(f"  НМЦК: {float(tender.initial_price):,.0f} ₽" if tender.initial_price else "  НМЦК: —")
    print(f"  Требований: {len(req_dicts)}")
    print(f"  Балл соответствия: {match_result['overall_match_score']:.1%}")
    print(f"  • Квалификация:  {match_result['qualification_score']:.1%}")
    print(f"  • Финансы:       {match_result['financial_score']:.1%}")
    print(f"  • Технические:   {match_result['technical_score']:.1%}")
    print(f"  • Документация:  {match_result['documentation_score']:.1%}")
    print(f"  Вероятность победы: {win_prob:.1%}")
    print(f"  Рисков: {len(risk_flags)} (общий уровень: {overall_risk})")
    print(f"  Рекомендация: {match_result['recommendation']}")
    print(f"{'━'*60}\n")

    return analysis


def main():
    create_tables()
    db = SessionLocal()

    try:
        # Create company profile
        logger.info("Создание профиля компании...")
        company = CompanyProfile(
            name='ООО "ИТ-Системы и Решения"',
            inn="7712345678",
            ogrn="1187746123456",
            legal_address="г. Москва, ул. Ленина, д. 10, оф. 205",
            okpd2_codes=["62.01", "62.02", "62.03", "63.11"],
            founding_year=2016,
            annual_revenue=12_000_000,
            annual_revenue_prev=9_500_000,
            staff_count=45,
            licenses=[
                {"name": "Лицензия ФСТЭК России на ТЗКИ", "type": "ФСТЭК", "number": "Л-0123-456"},
                {"name": "Лицензия ФСБ России на шифровальные средства", "type": "ФСБ", "number": "МФ-123/456"},
                {"name": "Сертификат ISO 27001", "type": "ISO", "number": "ISO-27001-2023"},
            ],
            smp_status=True,
            past_contracts=[
                {"number": "0372100001223000001", "customer": "Минцифры России", "amount": 3_500_000, "year": 2023, "subject": "Техническая поддержка серверной инфраструктуры"},
                {"number": "0372100001223000002", "customer": "ФНС России", "amount": 2_800_000, "year": 2023, "subject": "IT-услуги администрирование Linux серверов"},
                {"number": "0372100001222000003", "customer": "Росстат", "amount": 1_900_000, "year": 2022, "subject": "Обслуживание вычислительного оборудования"},
                {"number": "0372100001222000004", "customer": "МВД России", "amount": 4_200_000, "year": 2022, "subject": "Разработка программного обеспечения"},
                {"number": "0372100001221000005", "customer": "Минздрав России", "amount": 2_100_000, "year": 2021, "subject": "Техническое обслуживание медицинского оборудования"},
                {"number": "0372100001221000006", "customer": "ГБУЗ ГКБ №3", "amount": 850_000, "year": 2021, "subject": "Поставка и настройка компьютерного оборудования"},
                {"number": "0372100001220000007", "customer": "Пенсионный фонд", "amount": 3_100_000, "year": 2020, "subject": "IT-услуги техническая поддержка"},
                {"number": "0372100001220000008", "customer": "ФСС России", "amount": 1_500_000, "year": 2020, "subject": "Обслуживание сетевого оборудования"},
            ],
            authorized_person="Иванов Иван Иванович",
            authorized_person_position="Генеральный директор",
            bank_details={
                "bank_name": "ПАО Сбербанк",
                "account": "40702810200000012345",
                "corr_account": "30101810400000000225",
                "bik": "044525225",
            },
        )
        db.add(company)
        db.flush()
        logger.info(f"Компания создана: id={company.id}, name={company.name}")

        # Create tenders
        tenders_data = [
            {
                "title": "Поставка медицинского оборудования (аппараты УЗИ)",
                "external_id": "0372200097524000001",
                "customer_name": "ГБУЗ «Городская клиническая больница № 1»",
                "customer_inn": "7701234567",
                "submission_deadline": datetime.now() + timedelta(days=30),
                "contract_execution_deadline": datetime.now() + timedelta(days=60),
                "initial_price": 5_000_000,
                "purchase_subject": "Поставка аппаратов УЗИ экспертного класса",
                "okpd2_codes": ["26.60.11"],
                "law_type": "FZ_44",
                "full_text": TENDER_1_TEXT,
                "status": "NEW",
            },
            {
                "title": "Техническая поддержка серверной инфраструктуры",
                "external_id": "0372200097524000002",
                "customer_name": "ФКУ «ЦОД Минфина»",
                "customer_inn": "7702345678",
                "submission_deadline": datetime.now() + timedelta(days=25),
                "contract_execution_deadline": datetime.now() + timedelta(days=390),
                "initial_price": 2_500_000,
                "purchase_subject": "Услуги технической поддержки ИТ-инфраструктуры",
                "okpd2_codes": ["62.02.30", "63.11.12"],
                "law_type": "FZ_44",
                "full_text": TENDER_2_TEXT,
                "status": "NEW",
            },
            {
                "title": "Строительные работы по реконструкции административного здания",
                "external_id": "0372200097524000003",
                "customer_name": "Администрация Московского района",
                "customer_inn": "7709876543",
                "submission_deadline": datetime.now() + timedelta(days=35),
                "contract_execution_deadline": datetime.now() + timedelta(days=215),
                "initial_price": 15_000_000,
                "purchase_subject": "Реконструкция административного здания",
                "okpd2_codes": ["41.20.4"],
                "law_type": "FZ_44",
                "full_text": TENDER_3_TEXT,
                "status": "NEW",
            },
        ]

        tender_objects = []
        for td in tenders_data:
            tender = Tender(**td)
            db.add(tender)
            tender_objects.append(tender)
        db.flush()
        logger.info(f"Создано тендеров: {len(tender_objects)}")

        # Init modules
        parser = DocumentParser()
        matcher = RequirementMatcher()
        risk_analyzer = RiskAnalyzer()
        doc_generator = DocumentGenerator()
        win_model = WinProbabilityModel()

        # Run pipeline for each tender
        analyses = []
        for tender in tender_objects:
            analysis = run_pipeline(
                db, tender, company,
                parser, matcher, risk_analyzer, doc_generator, win_model,
            )
            analyses.append(analysis)

        # Add some participation history for model calibration
        history_data = [
            {"tender": tender_objects[1], "won": True},
            {"tender": tender_objects[0], "won": False, "rejection_reason": "Не является субъектом МСП"},
        ]
        for hd in history_data:
            h = ParticipationHistory(
                company_id=company.id,
                tender_id=hd["tender"].id,
                submitted_at=datetime.now(),
                won=hd.get("won"),
                rejection_reason=hd.get("rejection_reason"),
            )
            db.add(h)
        db.commit()

        print("\n" + "="*60)
        print("ДЕМО-ДАННЫЕ УСПЕШНО ЗАГРУЖЕНЫ И ОБРАБОТАНЫ")
        print("="*60)
        print(f"  Компания:  {company.name} (ID: {company.id})")
        print(f"  Тендеров:  {len(tender_objects)}")
        print(f"  Анализов:  {len(analyses)}")
        print()
        print("  Запустите UI: streamlit run ui/app.py")
        print("  Запустите API: python api/main.py")
        print("="*60 + "\n")

    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при загрузке демо-данных: {e}", exc_info=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
