"""Telegram-native message and inline-button editor."""
from __future__ import annotations
import json
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from ..branding import send_branded, keyboard_from_buttons

def allowed(update: Update, owner_id: int, admins: set[int] | None = None) -> bool:
    """Branding and system message editing are Owner-only."""
    user = update.effective_user
    return bool(user and user.id == owner_id)

async def texts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update, context.application.bot_data["owner_id"]):
        return
    keys = sorted(context.application.bot_data["defaults"].keys())
    listing = "**Message Editor**\n\n" + "\n".join(f"• {key} — /edittext {key}" for key in keys)
    data = context.application.bot_data
    await send_branded(context.bot, update.effective_chat.id, listing,
        image_url=data["image_url"], image_path=data["image_path"], small_caps=data["small_caps"])

async def edittext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update, context.application.bot_data["owner_id"]):
        return
    if not context.args:
        msg = "Usage: /edittext TEMPLATE_KEY"
    else:
        key = context.args[0]
        defaults = context.application.bot_data["defaults"]
        if key not in defaults:
            msg = f"Unknown template key: {key}. Use /texts."
        else:
            context.user_data["editing_text_key"] = key
            current = await context.application.bot_data["db"].get_text(
                context.application.bot_data["clone_id"], key, defaults[key])
            msg = f"Editing {key}. Send the complete replacement text now.\n\nCurrent value:\n{current}"
    data = context.application.bot_data
    await send_branded(context.bot, update.effective_chat.id, msg,
        image_url=data["image_url"], image_path=data["image_path"], small_caps=data["small_caps"])

async def previewtext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update, context.application.bot_data["owner_id"]):
        return
    if not context.args:
        body, markup = "Usage: /previewtext TEMPLATE_KEY", None
    else:
        key = context.args[0]
        defaults = context.application.bot_data["defaults"]
        if key not in defaults:
            body, markup = "Unknown template key. Use /texts.", None
        else:
            body = await context.application.bot_data["db"].get_text(
                context.application.bot_data["clone_id"], key, defaults[key])
            rows = await context.application.bot_data["db"].get_buttons(
                context.application.bot_data["clone_id"], key)
            markup = keyboard_from_buttons(rows)
    data = context.application.bot_data
    await send_branded(context.bot, update.effective_chat.id, body,
        image_url=data["image_url"], image_path=data["image_path"],
        small_caps=data["small_caps"], reply_markup=markup)

async def resettext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update, context.application.bot_data["owner_id"]):
        return
    if not context.args:
        body = "Usage: /resettext TEMPLATE_KEY"
    else:
        key = context.args[0]
        if key not in context.application.bot_data["defaults"]:
            body = "Unknown template key. Use /texts."
        else:
            await context.application.bot_data["db"].reset_text(
                context.application.bot_data["clone_id"], key)
            body = f"Default template restored: {key}"
    data = context.application.bot_data
    await send_branded(context.bot, update.effective_chat.id, body,
        image_url=data["image_url"], image_path=data["image_path"], small_caps=data["small_caps"])

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update, context.application.bot_data["owner_id"]):
        return
    if not context.args:
        body = "Usage: /buttons TEMPLATE_KEY"
    else:
        key = context.args[0]
        if key not in context.application.bot_data["defaults"]:
            body = "Unknown template key."
        else:
            rows = await context.application.bot_data["db"].get_buttons(
                context.application.bot_data["clone_id"], key)
            body = (
                f"Buttons for {key}:\n"
                f"{json.dumps(rows, ensure_ascii=False, indent=2)}\n\n"
                f"Use /addbutton {key} | LABEL | URL or /delbutton {key} | BUTTON_INDEX."
            )
    data = context.application.bot_data
    await send_branded(context.bot, update.effective_chat.id, body,
        image_url=data["image_url"], image_path=data["image_path"], small_caps=data["small_caps"])

async def addbutton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update, context.application.bot_data["owner_id"]):
        return
    raw = update.effective_message.text.partition(" ")[2]
    parts = [part.strip() for part in raw.split("|", 2)]
    if len(parts) != 3:
        body = "Usage: /addbutton TEMPLATE_KEY | BUTTON LABEL | https://example.com"
    else:
        key, label, url = parts
        if key not in context.application.bot_data["defaults"] or not url.startswith(("https://", "http://")):
            body = "Invalid template key or URL. Only HTTP(S) URLs are accepted."
        else:
            rows = await context.application.bot_data["db"].get_buttons(
                context.application.bot_data["clone_id"], key)
            rows.append([{"text": label[:64], "url": url}])
            await context.application.bot_data["db"].set_buttons(
                context.application.bot_data["clone_id"], key, rows)
            body = f"Button added to {key}. Preview with /previewtext {key}."
    data = context.application.bot_data
    await send_branded(context.bot, update.effective_chat.id, body,
        image_url=data["image_url"], image_path=data["image_path"], small_caps=data["small_caps"])

async def delbutton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update, context.application.bot_data["owner_id"]):
        return
    raw = update.effective_message.text.partition(" ")[2]
    parts = [part.strip() for part in raw.split("|", 1)]
    if len(parts) != 2:
        body = "Usage: /delbutton TEMPLATE_KEY | BUTTON_INDEX (1-based)"
    else:
        key, index_text = parts
        try:
            index = int(index_text) - 1
        except ValueError:
            index = -1
        if key not in context.application.bot_data["defaults"] or index < 0:
            body = "Invalid template key or button index."
        else:
            rows = await context.application.bot_data["db"].get_buttons(
                context.application.bot_data["clone_id"], key)
            flat = [button for row in rows for button in row]
            if index >= len(flat):
                body = "Button index not found."
            else:
                del flat[index]
                await context.application.bot_data["db"].set_buttons(
                    context.application.bot_data["clone_id"], key, [[button] for button in flat])
                body = f"Button removed from {key}."
    data = context.application.bot_data
    await send_branded(context.bot, update.effective_chat.id, body,
        image_url=data["image_url"], image_path=data["image_path"], small_caps=data["small_caps"])

async def editbutton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update, context.application.bot_data["owner_id"]):
        return
    raw = update.effective_message.text.partition(" ")[2]
    parts = [part.strip() for part in raw.split("|", 3)]
    if len(parts) != 4:
        body = "Usage: /editbutton TEMPLATE_KEY | BUTTON_INDEX | LABEL | URL (1-based)"
    else:
        key, index_text, label, url = parts
        try:
            index = int(index_text) - 1
        except ValueError:
            index = -1
        if (key not in context.application.bot_data["defaults"] or index < 0
                or not url.startswith(("https://", "http://"))):
            body = "Invalid template key, index or HTTP(S) URL."
        else:
            rows = await context.application.bot_data["db"].get_buttons(
                context.application.bot_data["clone_id"], key)
            flat = [button for row in rows for button in row]
            if index >= len(flat):
                body = "Button index not found."
            else:
                flat[index] = {"text": label[:64], "url": url}
                await context.application.bot_data["db"].set_buttons(
                    context.application.bot_data["clone_id"], key, [[button] for button in flat])
                body = f"Button updated for {key}. Preview with /previewtext {key}."
    data = context.application.bot_data
    await send_branded(context.bot, update.effective_chat.id, body,
        image_url=data["image_url"], image_path=data["image_path"], small_caps=data["small_caps"])

async def capture_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = context.user_data.get("editing_text_key")
    if not key or not update.effective_message or not update.effective_message.text:
        return
    if not allowed(update, context.application.bot_data["owner_id"]):
        context.user_data.pop("editing_text_key", None)
        return
    target_clone = context.user_data.pop("editing_clone_id", context.application.bot_data["clone_id"])
    await context.application.bot_data["db"].set_text(target_clone, key, update.effective_message.text)
    context.user_data.pop("editing_text_key", None)
    data = context.application.bot_data
    await send_branded(context.bot, update.effective_chat.id,
        f"Saved {key}. Preview it using /previewtext {key}.",
        image_url=data["image_url"], image_path=data["image_path"], small_caps=data["small_caps"])

def add_editor_handlers(app):
    app.add_handler(CommandHandler("texts", texts))
    app.add_handler(CommandHandler("edittext", edittext))
    app.add_handler(CommandHandler("previewtext", previewtext))
    app.add_handler(CommandHandler("resettext", resettext))
    app.add_handler(CommandHandler("buttons", buttons))
    app.add_handler(CommandHandler("addbutton", addbutton))
    app.add_handler(CommandHandler("editbutton", editbutton))
    app.add_handler(CommandHandler("delbutton", delbutton))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, capture_edit), group=-1)
