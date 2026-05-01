from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "3d-printing-api"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # Upload settings
    upload_dir: Path = Path("uploads")
    max_upload_size_bytes: int = 50 * 1024 * 1024  # 50 MB
    allowed_extensions: frozenset[str] = frozenset({".stl"})


settings = Settings()
