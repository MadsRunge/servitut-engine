import json
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "change-me-in-env"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    LLM_PROVIDER: str = "anthropic"
    ANTHROPIC_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    MODEL: str = "claude-sonnet-4-6"
    EXTRACTION_LLM_PROVIDER: str = ""
    EXTRACTION_MODEL: str = ""
    REPORT_LLM_PROVIDER: str = ""
    REPORT_MODEL: str = ""
    LLM_TIMEOUT_SECONDS: int = 120
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/servitut"
    REDIS_URL: str = "redis://localhost:6379/0"
    CORS_ALLOW_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    CORS_ALLOW_CREDENTIALS: bool = True
    STORAGE_DIR: str = "storage"
    PROMPTS_DIR: str = "prompts"
    MAX_CHUNK_SIZE: int = 2000
    CHUNK_OVERLAP: int = 200
    EXTRACTION_MAX_CONCURRENCY: int = 4
    OCR_LANGUAGE: str = "dan+eng"
    OCR_DESKEW: bool = True
    OCR_JOBS: int = 0
    OCR_BATCH_SIZE: int = 80
    CELERY_WORKER_CONCURRENCY: int = 2
    CELERY_LOGLEVEL: str = "info"
    APP_PIN: str = ""
    TINGLYSNING_DOWNLOAD_DIR: str = "~/Downloads"
    TMV_JOB_DOWNLOAD_DIR: str = "~/Downloads/servitut-engine-tmv"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def storage_path(self) -> Path:
        return Path(self.STORAGE_DIR)

    @property
    def cases_path(self) -> Path:
        return Path(self.STORAGE_DIR) / "cases"

    @property
    def prompts_path(self) -> Path:
        return Path(self.PROMPTS_DIR)

    @property
    def cors_allowed_origins(self) -> list[str]:
        raw_value = self.CORS_ALLOW_ORIGINS.strip()
        if not raw_value:
            return []

        if raw_value.startswith("[") or raw_value.startswith("{"):
            parsed = json.loads(raw_value)
            if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
                raise ValueError("CORS_ALLOW_ORIGINS must be a JSON string array")
            return [origin.strip() for origin in parsed if origin.strip()]

        return [origin.strip() for origin in raw_value.split(",") if origin.strip()]

    @property
    def tinglysning_download_path(self) -> Path:
        return Path(self.TINGLYSNING_DOWNLOAD_DIR).expanduser()


settings = Settings()
