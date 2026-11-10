"""Shared settings and branded command registration."""
from __future__ import annotations
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes
from .branding import close_keyboard, send_branded
from .branding_config import FOOTER_MESSAGE
from .formatting import render_text

def _navigation_keyboard(bot_data: dict, page: str, *, include_close: bool = True):
    rows = [[InlineKeyboardButton("· ᴀʙᴏᴜᴛ ·", callback_data="nav:about")]]
    channel_url = bot_data.get("channel_url")
    if channel_url:
        rows[0].append(InlineKeyboardButton("· ᴄʜᴀɴɴᴇʟ ·", url=channel_url))
    if page == "start":
        rows.append([InlineKeyboardButton("· ʜᴇʟᴘ ·", callback_data="nav:help")])
    else:
        rows.append([
            InlineKeyboardButton("· ʜᴇʟᴘ ·", callback_data="nav:help"),
            InlineKeyboardButton("· ʙᴀᴄᴋ ·", callback_data="nav:start"),
        ])
    if include_close:
        rows.extend(close_keyboard().inline_keyboard)
    return InlineKeyboardMarkup(rows)

async def _page_body(context: ContextTypes.DEFAULT_TYPE, page: str, first_name: str = "there") -> str:
    key = f"file.{page}"
    fallback = context.application.bot_data["defaults"].get(key, "Welcome!")
    body = await context.application.bot_data["db"].get_text(
        context.application.bot_data["clone_id"], key, fallback
    )
    return body.replace("{first_name}", first_name)

async def _send_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: str):
    first_name = update.effective_user.first_name if update.effective_user else "there"
    body = await _page_body(context, page, first_name or "there")
    await send_branded(
        context.bot, update.effective_chat.id, body,
        image_url=context.application.bot_data["image_url"],
        image_path=context.application.bot_data["image_path"],
        small_caps=context.application.bot_data["small_caps"],
        reply_markup=_navigation_keyboard(context.application.bot_data, page, include_close=False),
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.application.bot_data["product"] == "file" and context.args:
        return
    if update.effective_user:
        user_row = await context.application.bot_data["db"].require().fetchrow(
            """INSERT INTO bot_users(clone_id,user_id) VALUES($1,$2)
               ON CONFLICT(clone_id,user_id) DO UPDATE SET last_seen=NOW()
               RETURNING is_banned""",
            context.application.bot_data["clone_id"], update.effective_user.id,
        )
        if user_row and user_row["is_banned"]:
            await send_branded(
                context.bot, update.effective_chat.id,
                context.application.bot_data["defaults"]["file.blocked"],
                image_url=context.application.bot_data["image_url"],
                image_path=context.application.bot_data["image_path"],
                small_caps=context.application.bot_data["small_caps"],
            )
            return
    await _send_page(update, context, "start")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_page(update, context, "help")

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_page(update, context, "about")

async def navigation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None or query.data not in {"nav:start", "nav:about", "nav:help"}:
        return
    page = query.data.split(":", 1)[1]
    first_name = query.from_user.first_name if query.from_user else "there"
    body = await _page_body(context, page, first_name or "there")
    if FOOTER_MESSAGE:
        body = f"{body}\n\n{FOOTER_MESSAGE}"
    markup = _navigation_keyboard(context.application.bot_data, page, include_close=True)
    try:
        if query.message is None:
            raise TelegramError("Navigation message is unavailable")
        await query.message.edit_caption(
            caption=render_text(body, small_caps=context.application.bot_data["small_caps"]),
            parse_mode="HTML", reply_markup=markup,
        )
        await query.answer()
    except TelegramError:
        try:
            await query.answer()
        except TelegramError:
            pass
        if query.message:
            await send_branded(
                context.bot, query.message.chat_id, body,
                image_url=context.application.bot_data["image_url"],
                image_path=context.application.bot_data["image_path"],
                small_caps=context.application.bot_data["small_caps"],
                reply_markup=_navigation_keyboard(context.application.bot_data, page, include_close=False),
            )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_branded(
        context.bot, update.effective_chat.id, "Pong! The bot is responding.",
        image_url=context.application.bot_data["image_url"],
        image_path=context.application.bot_data["image_path"],
        small_caps=context.application.bot_data["small_caps"],
    )

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = context.application.bot_data
    if not user or (user.id != data["owner_id"] and user.id not in data["admins"]):
        return
    body = (
        "**Settings**\n\n"
        "/texts — edit messages\n"
        "/buttons TEMPLATE_KEY — manage inline buttons\n"
        "/dlt_time SECONDS — set delivery auto-delete\n"
        "/setmaxfiles LIMIT — change the default file limit\n"
        "/help — command guide"
    )
    await send_branded(
        context.bot, update.effective_chat.id, body,
        image_url=data["image_url"], image_path=data["image_path"], small_caps=data["small_caps"],
    )

def add_common_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CallbackQueryHandler(navigation_callback, pattern=r"^nav:(start|about|help)$"))
