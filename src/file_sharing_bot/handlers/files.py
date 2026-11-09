from __future__ import annotations
import secrets
import logging
from datetime import timedelta
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from ..branding import send_branded, keyboard_from_buttons

log = logging.getLogger(__name__)

async def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(update.effective_user and update.effective_user.id in context.application.bot_data["admins"] | {context.application.bot_data["owner_id"]})

async def genlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update, context): return
    if len(context.args) != 2:
        body = "Usage: `/genlink STORAGE_CHANNEL_ID MESSAGE_ID`\nThe source must be in the official storage channel and accessible to this bot."
    else:
        try:
            chat_id, message_id = int(context.args[0]), int(context.args[1])
            token = secrets.token_urlsafe(12)
            db = context.application.bot_data["db"]
            await db.require().execute(
                "INSERT INTO file_share_links(clone_id,token,source_chat_id,message_ids,created_by) VALUES($1,$2,$3,$4,$5)",
                context.application.bot_data["clone_id"], token, chat_id, [message_id], update.effective_user.id,
            )
            me = await context.bot.get_me()
            body = (await db.get_text(context.application.bot_data["clone_id"], "file.link_created",
                    context.application.bot_data["defaults"]["file.link_created"])).format(url=f"https://t.me/{me.username}?start={token}")
        except (ValueError, TypeError):
            body = "Channel ID and message ID must be numeric."
    rows = await context.application.bot_data["db"].get_buttons(context.application.bot_data["clone_id"], "file.link_created")
    markup = keyboard_from_buttons(rows, small_caps=context.application.bot_data["small_caps"])
    await send_branded(context.bot, update.effective_chat.id, body,
        image_url=context.application.bot_data["image_url"], image_path=context.application.bot_data["image_path"],
        small_caps=context.application.bot_data["small_caps"], reply_markup=markup)

async def batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update, context): return
    if len(context.args) != 3:
        body = "Usage: `/batch STORAGE_CHANNEL_ID FIRST_MESSAGE_ID LAST_MESSAGE_ID` (maximum 100 messages)."
    else:
        try:
            chat_id, first_id, last_id = map(int, context.args)
            if first_id <= 0 or last_id < first_id or last_id - first_id + 1 > 100:
                raise ValueError
            token = secrets.token_urlsafe(12)
            ids = list(range(first_id, last_id + 1))
            await context.application.bot_data["db"].require().execute(
                "INSERT INTO file_share_links(clone_id,token,source_chat_id,message_ids,created_by) VALUES($1,$2,$3,$4,$5)",
                context.application.bot_data["clone_id"], token, chat_id, ids, update.effective_user.id,
            )
            me = await context.bot.get_me()
            body = f"✅ ʙᴀᴛᴄʜ ʟɪɴᴋ ᴄʀᴇᴀᴛᴇᴅ ғᴏʀ {len(ids)} ᴍᴇssᴀɢᴇs:\nhttps://t.me/{me.username}?start={token}"
        except (ValueError, TypeError):
            body = "Invalid range. Use numeric IDs and a range of 1–100 messages."
    rows = await context.application.bot_data["db"].get_buttons(context.application.bot_data["clone_id"], "file.link_created")
    markup = keyboard_from_buttons(rows, small_caps=context.application.bot_data["small_caps"])
    await send_branded(context.bot, update.effective_chat.id, body,
        image_url=context.application.bot_data["image_url"], image_path=context.application.bot_data["image_path"],
        small_caps=context.application.bot_data["small_caps"], reply_markup=markup)

async def deliver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    token = context.args[0]
    db = context.application.bot_data["db"]
    clone_id = context.application.bot_data["clone_id"]
    row = await db.require().fetchrow(
        "SELECT * FROM file_share_links WHERE clone_id=$1 AND token=$2 AND is_active=TRUE", clone_id, token
    )
    if not row:
        await _reply(context, update, context.application.bot_data["defaults"]["file.expired"])
        await db.require().execute(
            "INSERT INTO file_delivery_events(clone_id,token,user_id,status,detail) VALUES($1,$2,$3,'failed','missing_or_inactive')",
            clone_id, token, update.effective_user.id,
        )
        return
    ids = list(row["message_ids"] or [])
    limit = int(context.application.bot_data["max_files_per_user"])
    if len(ids) > limit:
        await _reply(context, update, f"ᴛʜɪs ʙᴀᴛᴄʜ ʜᴀs {len(ids)} ғɪʟᴇs; ᴘᴇʀ-ᴜsᴇʀ ʟɪᴍɪᴛ ɪs {limit}.")
        return
    await _reply(context, update, context.application.bot_data["defaults"]["file.delivery_started"])
    success = 0
    for message_id in ids:
        try:
            copied = await context.bot.copy_message(
                chat_id=update.effective_chat.id, from_chat_id=row["source_chat_id"], message_id=message_id,
                protect_content=bool(context.application.bot_data.get("protect_content", True)),
            )
            success += 1
            auto_delete = int(context.application.bot_data["default_auto_delete"])
            if auto_delete > 0 and context.job_queue:
                context.job_queue.run_once(_delete_delivered, when=auto_delete,
                    data={"chat_id": update.effective_chat.id, "message_id": copied.message_id})
        except Exception as exc:
            log.warning("File copy failed (%s): %s", type(exc).__name__, str(exc)[:180])
    status = "success" if success == len(ids) else ("partial" if success else "failed")
    await db.require().execute(
        "INSERT INTO file_delivery_events(clone_id,token,user_id,status,detail) VALUES($1,$2,$3,$4,$5)",
        clone_id, token, update.effective_user.id, status, f"{success}/{len(ids)} delivered",
    )
    await db.require().execute(
        "UPDATE file_share_links SET access_count=access_count+1 WHERE clone_id=$1 AND token=$2", clone_id, token
    )
    if success != len(ids):
        await _reply(context, update, f"ᴅᴇʟɪᴠᴇʀʏ ᴘᴀʀᴛɪᴀʟʟʏ ᴄᴏᴍᴘʟᴇᴛᴇ: {success}/{len(ids)}. ᴄʜᴇᴄᴋ sᴛᴏʀᴀɢᴇ ᴘᴇʀᴍɪssɪᴏɴs ᴀɴᴅ ʟᴏɢs.")

async def _delete_delivered(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    try:
        await context.bot.delete_message(chat_id=data["chat_id"], message_id=data["message_id"])
    except Exception as exc:
        log.info("Auto-delete skipped: %s", type(exc).__name__)

async def _reply(context, update, body):
    await send_branded(context.bot, update.effective_chat.id, body,
        image_url=context.application.bot_data["image_url"], image_path=context.application.bot_data["image_path"],
        small_caps=context.application.bot_data["small_caps"])

async def collections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await context.application.bot_data["db"].require().fetch(
        "SELECT collection_key,title,metadata FROM file_collections WHERE clone_id=$1 ORDER BY id DESC LIMIT 30",
        context.application.bot_data["clone_id"])
    if not rows:
        body = "ɴᴏ ᴄᴏʟʟᴇᴄᴛɪᴏɴs ʜᴀᴠᴇ ʙᴇᴇɴ ᴄʀᴇᴀᴛᴇᴅ ʏᴇᴛ."
    else:
        body = "**ᴄᴏʟʟᴇᴄᴛɪᴏɴs**\n\n" + "\n".join(f"{r['collection_key']} · {r['title']}" for r in rows)
    await _reply(context, update, body)

async def collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        body = "Usage: `/collection COLLECTION_ID`"
    else:
        row = await context.application.bot_data["db"].require().fetchrow(
            "SELECT collection_key,title,metadata,created_at FROM file_collections WHERE clone_id=$1 AND collection_key=$2",
            context.application.bot_data["clone_id"], context.args[0])
        body = f"**{row['title']}**\nID: `{row['collection_key']}`\nMetadata: `{row['metadata']}`" if row else "Collection not found."
    await _reply(context, update, body)

async def delivery_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update, context): return
    row = await context.application.bot_data["db"].require().fetchrow(
        "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE status='success') AS successful, COUNT(*) FILTER (WHERE status='failed') AS failed, COUNT(*) FILTER (WHERE status='partial') AS partial FROM file_delivery_events WHERE clone_id=$1",
        context.application.bot_data["clone_id"])
    body = f"**ᴅᴇʟɪᴠᴇʀʏ ᴀɴᴀʟʏᴛɪᴄs**\nTotal: {row['total']}\nSuccessful: {row['successful']}\nFailed: {row['failed']}\nPartial: {row['partial']}"
    await _reply(context, update, body)

async def dlt_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update, context): return
    if not context.args or not context.args[0].isdigit():
        body = "Usage: `/dlt_time SECONDS` (0 disables auto-delete)."
    else:
        seconds = int(context.args[0])
        if seconds < 0 or seconds > 86400:
            body = "Auto-delete must be between 0 and 86400 seconds."
        else:
            context.application.bot_data["default_auto_delete"] = seconds
            await context.application.bot_data["db"].require().execute(
                "INSERT INTO file_settings(clone_id,setting_key,setting_value) VALUES($1,'auto_delete',$2) ON CONFLICT(clone_id,setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value,updated_at=NOW()",
                context.application.bot_data["clone_id"], str(seconds))
            body = f"Auto-delete set to {seconds} seconds."
    await _reply(context, update, body)

async def storagehealth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update, context): return
    channel_id = context.application.bot_data.get("storage_channel_id")
    if not channel_id:
        body = "STORAGE_CHANNEL_ID is not configured."
    else:
        try:
            chat = await context.bot.get_chat(channel_id)
            body = f"Storage channel reachable: {chat.title} (`{channel_id}`). The bot still requires access to read/copy its messages."
        except Exception as exc:
            body = f"Storage channel check failed: {type(exc).__name__}. Verify membership and channel ID."
    await _reply(context, update, body)

async def regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update, context): return
    if not context.args or not context.args[0].isdigit():
        body = "Usage: `/regenerate SHARE_LINK_ID`"
    else:
        link_id = int(context.args[0]); token = secrets.token_urlsafe(12)
        row = await context.application.bot_data["db"].require().fetchrow(
            "UPDATE file_share_links SET token=$1 WHERE id=$2 AND clone_id=$3 RETURNING token",
            token, link_id, context.application.bot_data["clone_id"])
        if row:
            me = await context.bot.get_me(); body = f"New link: https://t.me/{me.username}?start={token}"
        else: body = "Share-link record not found."
    await _reply(context, update, body)

async def stream_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(context, update,
        "ᴅɪʀᴇᴄᴛ ʜᴛᴛᴘ sᴛʀᴇᴀᴍɪɴɢ ɪs ɴᴏᴛ ᴇɴᴀʙʟᴇᴅ ɪɴ ᴛʜɪs sᴄᴀғғᴏʟᴅ. ɪᴛ ʀᴇǫᴜɪʀᴇs ᴛʜᴇ sᴛʀᴇᴀᴍɪɴɢ ᴡᴇʙ ᴍᴏᴅᴜʟᴇ ᴀɴᴅ ᴅᴏᴍᴀɪɴ ᴄᴏɴғɪɢᴜʀᴀᴛɪᴏɴ.")

def add_file_handlers(app):
    app.add_handler(CommandHandler("genlink", genlink))
    app.add_handler(CommandHandler("batch", batch))
    app.add_handler(CommandHandler("collections", collections))
    app.add_handler(CommandHandler("collection", collection))
    app.add_handler(CommandHandler("delivery_stats", delivery_stats))
    app.add_handler(CommandHandler("dlt_time", dlt_time))
    app.add_handler(CommandHandler("storagehealth", storagehealth))
    app.add_handler(CommandHandler("regenerate", regenerate))
    app.add_handler(CommandHandler("link", stream_link))
    # /start payload handler is registered separately after the common /start handler.
    app.add_handler(CommandHandler("start", deliver), group=1)
