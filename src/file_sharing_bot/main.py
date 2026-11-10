from __future__ import annotations
import logging
import os
from pathlib import Path
from telegram.ext import ApplicationBuilder, CallbackQueryHandler
from .config import Settings
from .database import Database
from .defaults import DEFAULT_MESSAGES
from .settings import add_common_handlers
from .message_editor.handlers import add_editor_handlers
from .handlers.files import add_file_handlers
from .errors import error_handler
from .branding import close_branded_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

async def post_init(app):
    settings = app.bot_data["settings"]
    db = Database(settings.database_url)
    await db.connect()
    migrations_dir = Path(__file__).resolve().parents[2] / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))
    if not migration_files:
        raise RuntimeError(f"No database migrations found in {migrations_dir}")
    for migration_file in migration_files:
        await db.init_schema(migration_file.read_text(encoding="utf-8"))
    app.bot_data["db"] = db
    rows = await db.require().fetch(
        "SELECT setting_key, setting_value FROM file_settings WHERE clone_id=$1", settings.clone_id
    )
    saved = {row["setting_key"]: row["setting_value"] for row in rows}
    app.bot_data["default_auto_delete"] = int(saved.get("auto_delete", settings.default_auto_delete))
    app.bot_data["max_files_per_user"] = int(saved.get("max_files_per_user", settings.max_files_per_user))

async def post_shutdown(app):
    db = app.bot_data.get("db")
    if db:
        await db.close()

def main():
    settings = Settings.from_env()
    admins = {
        int(value) for value in os.getenv("ADMINS", "").replace(",", " ").split() if value.isdigit()
    }
    app = (
        ApplicationBuilder().token(settings.bot_token)
        .post_init(post_init).post_shutdown(post_shutdown).build()
    )
    app.bot_data.update({
        "settings": settings, "owner_id": settings.owner_id, "admins": admins,
        "clone_id": settings.clone_id, "image_url": settings.branding_image_url,
        "image_path": settings.branding_image_path, "small_caps": settings.small_caps,
        "channel_url": settings.channel_url, "defaults": DEFAULT_MESSAGES, "product": "file",
        "storage_channel_id": settings.storage_channel_id,
        "default_auto_delete": settings.default_auto_delete,
        "max_files_per_user": settings.max_files_per_user, "protect_content": True,
    })
    app.add_handler(CallbackQueryHandler(close_branded_message, pattern=r"^branding:close$"), group=-1)
    add_common_handlers(app)
    add_editor_handlers(app)
    add_file_handlers(app)
    app.add_error_handler(error_handler)
    app.run_polling(allowed_updates=["message", "callback_query", "chat_member"])

if __name__ == "__main__":
    main()
