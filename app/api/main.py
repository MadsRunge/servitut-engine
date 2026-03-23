from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.error_handlers import register_exception_handlers
from app.api.health import build_health_payload
from app.api.routes import auth, cases, documents, extraction, jobs, ocr, reports
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.database import initialize_database

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Servitut Engine API",
    description="API til udtræk og redegørelse af servitutter fra PDF-dokumenter",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(cases.router, prefix="/cases", tags=["cases"])
app.include_router(documents.router, prefix="/cases", tags=["documents"])
app.include_router(jobs.router, prefix="/cases", tags=["jobs"])
app.include_router(ocr.router, prefix="/cases", tags=["ocr"])
app.include_router(extraction.router, prefix="/cases", tags=["extraction"])
app.include_router(reports.router, prefix="/cases", tags=["reports"])


@app.get("/health")
def health():
    status_code, payload = build_health_payload()
    return JSONResponse(status_code=status_code, content=payload)
