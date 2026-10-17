from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_", env_file=".env", extra="ignore")
    env: str = "development"
    workspace: Path = Path("./data/workspace")
    database_path: Path = Path("./data/nova.sqlite3")
    audit_path: Path = Path("./data/audit.jsonl")
    api_token_file: Path = Path("./data/api.token")
    litert_base_url: str = "http://127.0.0.1:9379/v1"
    litert_model: str = "local-model"
    whisper_cli_path: str = ""
    whisper_model_path: Path = Path("./data/models/whisper/ggml-base.bin")
    whisper_timeout_seconds: int = 180
    whisper_max_upload_bytes: int = 25000000
    piper_cli_path: str = ""
    piper_model_path: Path = Path("./data/models/piper/voice.onnx")
    llama_cpp_server_path: str = ""
    onnxruntime_enabled: bool = True
    huggingface_cache_dir: Path = Path("./data/models/huggingface")
    huggingface_max_download_bytes: int = 2000000000
    huggingface_token: str = ""
    require_approval_for_writes: bool = True

settings = Settings()
