from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
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
    STORAGE_DIR: str = "storage"
    PROMPTS_DIR: str = "prompts"
    MAX_CHUNK_SIZE: int = 2000
    CHUNK_OVERLAP: int = 200
    EXTRACTION_MAX_CONCURRENCY: int = 4
    OCR_LANGUAGE: str = "dan+eng"
    OCR_DESKEW: bool = True
    OCR_JOBS: int = 0
    OCR_BATCH_SIZE: int = 80
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
    def tinglysning_download_path(self) -> Path:
        return Path(self.TINGLYSNING_DOWNLOAD_DIR).expanduser()


settings = Settings()
