"""Environment and mounted-secret configuration."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
from .branding_config import IMAGE_URL as BRANDING_IMAGE_DEFAULT
from .branding_config import SMALL_CAPS as BRANDING_SMALL_CAPS

load_dotenv()

def _load_config_file() -> dict:
    path = os.getenv("CONFIG_FILE")
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.is_file():
        raise RuntimeError(f"CONFIG_FILE does not exist: {path}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("CONFIG_FILE must contain a JSON object.")
    return data

_FILE_CONFIG = _load_config_file()

def value(name: str, default=None):
    return os.getenv(name, _FILE_CONFIG.get(name, default))

@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_url: str
    owner_id: int
    clone_id: str
    branding_image_url: str
    branding_image_path: str | None
    small_caps: bool
    storage_channel_id: int | None = None
    storage_api_url: str | None = None
    storage_api_key: str | None = None
    channel_url: str | None = None
    default_auto_delete: int = 0
    max_files_per_user: int = 50

    @classmethod
    def from_env(cls) -> "Settings":
        token = value("BOT_TOKEN")
        dsn = value("DATABASE_URL")
        owner = value("OWNER_ID", "0")
        if not token:
            raise RuntimeError("BOT_TOKEN is required (or provide CONFIG_FILE).")
        if not dsn:
            raise RuntimeError("DATABASE_URL is required.")
        try:
            owner_id = int(owner)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("OWNER_ID must be a numeric Telegram user ID.") from exc
        storage_channel = value("STORAGE_CHANNEL_ID")
        try:
            storage_channel_id = int(storage_channel) if storage_channel else None
            auto_delete = int(value("DEFAULT_AUTO_DELETE", "0"))
            max_files = int(value("MAX_FILES_PER_USER", "50"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Storage channel, auto-delete and file-limit settings must be numeric.") from exc
        if auto_delete < 0 or auto_delete > 86400:
            raise RuntimeError("DEFAULT_AUTO_DELETE must be between 0 and 86400 seconds.")
        if max_files < 1:
            raise RuntimeError("MAX_FILES_PER_USER must be at least 1.")
        channel_url = value("CHANNEL_URL")
        if channel_url and not str(channel_url).startswith(("https://t.me/", "https://telegram.me/")):
            raise RuntimeError("CHANNEL_URL must be a Telegram HTTPS link.")
        return cls(
            bot_token=str(token), database_url=str(dsn), owner_id=owner_id,
            clone_id=str(value("CLONE_ID", "official")),
            branding_image_url=str(value("BRANDING_IMAGE_URL", BRANDING_IMAGE_DEFAULT)),
            branding_image_path=value("BRANDING_IMAGE_PATH"),
            small_caps=str(value("SMALL_CAPS", str(BRANDING_SMALL_CAPS))).lower() in {"1", "true", "yes", "on"},
            storage_channel_id=storage_channel_id,
            storage_api_url=value("STORAGE_API_URL"),
            storage_api_key=value("STORAGE_API_KEY"),
            channel_url=str(channel_url) if channel_url else None,
            default_auto_delete=auto_delete,
            max_files_per_user=max_files,
        )
