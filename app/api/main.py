from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import cases, documents, extraction, reports
from app.core.logging import setup_logging

setup_logging()

app = FastAPI(
    title="Servitut Engine API",
    description="API til udtræk og redegørelse af servitutter fra PDF-dokumenter",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cases.router, prefix="/cases", tags=["cases"])
app.include_router(documents.router, prefix="/cases", tags=["documents"])
app.include_router(extraction.router, prefix="/cases", tags=["extraction"])
app.include_router(reports.router, prefix="/cases", tags=["reports"])


@app.get("/health")
def health():
    return {"status": "ok"}
