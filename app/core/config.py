from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    LLM_PROVIDER: str = "anthropic"
    ANTHROPIC_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    MODEL: str = "claude-sonnet-4-6"
    LLM_TIMEOUT_SECONDS: int = 120
    STORAGE_DIR: str = "storage"
    PROMPTS_DIR: str = "prompts"
    MAX_CHUNK_SIZE: int = 2000
    CHUNK_OVERLAP: int = 200

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


settings = Settings()
