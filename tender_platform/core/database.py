import os
import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_BASE_DIR / 'tender_platform.db'}")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables() -> None:
    from core.models import Base
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified.")


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
