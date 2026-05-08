import logging
import sys
from pathlib import Path

# Add project root to sys.path so imports work when running directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.database import create_tables
from api.routers import tenders, company, documents

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(
    title="TenderPlatform API",
    description="Интеллектуальная платформа автоматизации участия в государственных закупках (44-ФЗ, 223-ФЗ)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    create_tables()


app.include_router(tenders.router)
app.include_router(company.router)
app.include_router(documents.router)


@app.get("/")
def root():
    return {"status": "ok", "service": "TenderPlatform API v1.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
