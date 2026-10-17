from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_", env_file=".env", extra="ignore")
    env: str = "development"
    workspace: Path = Path("./data/workspace")
    database_path: Path = Path("./data/nova.sqlite3")
    audit_path: Path = Path("./data/audit.jsonl")
    api_token_file: Path = Path("./data/api.token")
    litert_base_url: str = "http://127.0.0.1:8080/v1"
    litert_model: str = "local-model"
    huggingface_cache_dir: Path = Path("./data/models/huggingface")
    huggingface_max_download_bytes: int = 2000000000
    require_approval_for_writes: bool = True

settings = Settings()
