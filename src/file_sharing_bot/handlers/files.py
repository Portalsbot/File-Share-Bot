from __future__ import annotations
import logging
import secrets
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from ..branding import close_keyboard, send_branded

log = logging.getLogger(__name__)

def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    data = context.application.bot_data
    return bool(user and (user.id == data["owner_id"] or user.id in data["admins"]))

def _is_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    return bool(user and user.id == context.application.bot_data["owner_id"])

async def _reply(context, update, body, reply_markup=None):
    data = context.application.bot_data
    return await send_branded(
        context.bot, update.effective_chat.id, body,
        image_url=data["image_url"], image_path=data["image_path"],
        small_caps=data["small_caps"], reply_markup=reply_markup,
    )

def _configured_storage_chat(context, chat_id: int) -> bool:
    configured = context.application.bot_data.get("storage_channel_id")
    return configured is not None and int(chat_id) == int(configured)

async def genlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context):
        return
    if len(context.args) != 2:
        body = "Usage: /genlink STORAGE_CHANNEL_ID MESSAGE_ID"
    else:
        try:
            chat_id, message_id = int(context.args[0]), int(context.args[1])
            if message_id <= 0 or not _configured_storage_chat(context, chat_id):
                raise ValueError
            token = secrets.token_urlsafe(12)
            db = context.application.bot_data["db"]
            await db.require().execute(
                """INSERT INTO file_share_links
                   (clone_id,token,source_chat_id,message_ids,created_by) VALUES($1,$2,$3,$4,$5)""",
                context.application.bot_data["clone_id"], token, chat_id, [message_id],
                update.effective_user.id,
            )
            me = await context.bot.get_me()
            body = (
                await db.get_text(
                    context.application.bot_data["clone_id"], "file.link_created",
                    context.application.bot_data["defaults"]["file.link_created"],
                )
            ).replace("{url}", f"https://t.me/{me.username}?start={token}")
        except (ValueError, TypeError):
            body = "Use the configured STORAGE_CHANNEL_ID and a positive numeric message ID."
    await _reply(context, update, body)

async def batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context):
        return
    if len(context.args) != 3:
        body = "Usage: /batch STORAGE_CHANNEL_ID FIRST_MESSAGE_ID LAST_MESSAGE_ID (maximum 100 messages)."
    else:
        try:
            chat_id, first_id, last_id = map(int, context.args)
            if (
                first_id <= 0 or last_id < first_id or last_id - first_id + 1 > 100
                or not _configured_storage_chat(context, chat_id)
            ):
                raise ValueError
            token = secrets.token_urlsafe(12)
            message_ids = list(range(first_id, last_id + 1))
            await context.application.bot_data["db"].require().execute(
                """INSERT INTO file_share_links
                   (clone_id,token,source_chat_id,message_ids,created_by) VALUES($1,$2,$3,$4,$5)""",
                context.application.bot_data["clone_id"], token, chat_id, message_ids,
                update.effective_user.id,
            )
            me = await context.bot.get_me()
            body = f"Batch link created for {len(message_ids)} messages:\nhttps://t.me/{me.username}?start={token}"
        except (ValueError, TypeError):
            body = "Invalid storage channel or range. Use the configured channel and a range of 1–100 messages."
    await _reply(context, update, body)

async def deliver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not update.effective_user:
        return
    token = context.args[0]
    db = context.application.bot_data["db"]
    clone_id = context.application.bot_data["clone_id"]
    user_id = update.effective_user.id

    user_row = await db.require().fetchrow(
        """INSERT INTO bot_users(clone_id,user_id) VALUES($1,$2)
           ON CONFLICT(clone_id,user_id) DO UPDATE SET last_seen=NOW()
           RETURNING is_banned, max_files_per_request""",
        clone_id, user_id,
    )
    if user_row and user_row["is_banned"]:
        await _reply(context, update, context.application.bot_data["defaults"]["file.blocked"])
        return

    row = await db.require().fetchrow(
        """SELECT * FROM file_share_links WHERE clone_id=$1 AND token=$2 AND is_active=TRUE""",
        clone_id, token,
    )
    if not row:
        await _reply(context, update, context.application.bot_data["defaults"]["file.expired"])
        await db.require().execute(
            """INSERT INTO file_delivery_events(clone_id,token,user_id,status,detail)
               VALUES($1,$2,$3,'failed','missing_or_inactive')""",
            clone_id, token, user_id,
        )
        return

    message_ids = list(row["message_ids"] or [])
    per_user_limit = (
        int(user_row["max_files_per_request"])
        if user_row and user_row["max_files_per_request"]
        else int(context.application.bot_data["max_files_per_user"])
    )
    if not message_ids:
        await _reply(context, update, context.application.bot_data["defaults"]["file.invalid"])
        return
    if len(message_ids) > per_user_limit:
        await _reply(
            context, update,
            context.application.bot_data["defaults"]["file.limit_exceeded"].format(
                file_count=len(message_ids), limit=per_user_limit
            ),
        )
        await db.require().execute(
            """INSERT INTO file_delivery_events(clone_id,token,user_id,status,detail)
               VALUES($1,$2,$3,'failed',$4)""",
            clone_id, token, user_id, f"per_request_limit:{per_user_limit}",
        )
        return

    await _reply(context, update, context.application.bot_data["defaults"]["file.delivery_started"])
    success = 0
    for message_id in message_ids:
        try:
            copied = await context.bot.copy_message(
                chat_id=update.effective_chat.id, from_chat_id=row["source_chat_id"],
                message_id=message_id,
                protect_content=bool(context.application.bot_data.get("protect_content", True)),
                reply_markup=close_keyboard(),
            )
            success += 1
            auto_delete = int(context.application.bot_data["default_auto_delete"])
            if auto_delete > 0 and context.job_queue:
                context.job_queue.run_once(
                    _delete_delivered, when=auto_delete,
                    data={"chat_id": update.effective_chat.id, "message_id": copied.message_id},
                )
        except Exception as exc:
            log.warning("File copy failed (%s): %s", type(exc).__name__, str(exc)[:180])

    status = "success" if success == len(message_ids) else ("partial" if success else "failed")
    await db.require().execute(
        """INSERT INTO file_delivery_events(clone_id,token,user_id,status,detail)
           VALUES($1,$2,$3,$4,$5)""",
        clone_id, token, user_id, status, f"{success}/{len(message_ids)} delivered",
    )
    await db.require().execute(
        """UPDATE file_share_links SET access_count=access_count+1 WHERE clone_id=$1 AND token=$2""",
        clone_id, token,
    )
    if success != len(message_ids):
        await _reply(
            context, update,
            context.application.bot_data["defaults"]["file.delivery_partial"].format(
                success=success, total=len(message_ids)
            ),
        )

async def _delete_delivered(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    try:
        await context.bot.delete_message(chat_id=data["chat_id"], message_id=data["message_id"])
    except Exception as exc:
        log.info("Auto-delete skipped: %s", type(exc).__name__)

async def collections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context):
        return
    rows = await context.application.bot_data["db"].require().fetch(
        """SELECT collection_key,title,metadata FROM file_collections
           WHERE clone_id=$1 ORDER BY id DESC LIMIT 30""",
        context.application.bot_data["clone_id"],
    )
    if not rows:
        body = "No File Collections have been created yet."
    else:
        body = "Your File Collections:\n" + "\n".join(
            f"{row['collection_key']} · {row['title']}" for row in rows
        )
    await _reply(context, update, body)

async def collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context):
        return
    if not context.args:
        body = "Usage: /collection COLLECTION_ID"
    else:
        row = await context.application.bot_data["db"].require().fetchrow(
            """SELECT collection_key,title,metadata,created_at FROM file_collections
               WHERE clone_id=$1 AND collection_key=$2""",
            context.application.bot_data["clone_id"], context.args[0],
        )
        if row:
            body = (
                f"**{row['title']}**\nID: {row['collection_key']}\n"
                f"Created: {row['created_at']}\nMetadata: {row['metadata']}"
            )
        else:
            body = "Collection not found."
    await _reply(context, update, body)

async def delivery_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context):
        return
    row = await context.application.bot_data["db"].require().fetchrow(
        """SELECT COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE status='success') AS successful,
                  COUNT(*) FILTER (WHERE status='failed') AS failed,
                  COUNT(*) FILTER (WHERE status='partial') AS partial
           FROM file_delivery_events WHERE clone_id=$1""",
        context.application.bot_data["clone_id"],
    )
    body = (
        "**Delivery Analytics**\n"
        f"Total: {row['total']}\nSuccessful: {row['successful']}\n"
        f"Failed: {row['failed']}\nPartial: {row['partial']}"
    )
    await _reply(context, update, body)

async def dlt_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context):
        return
    if not context.args or not context.args[0].isdigit():
        body = "Usage: /dlt_time SECONDS (0 disables auto-delete)."
    else:
        seconds = int(context.args[0])
        if seconds < 0 or seconds > 86400:
            body = "Auto-delete must be between 0 and 86400 seconds."
        else:
            context.application.bot_data["default_auto_delete"] = seconds
            await context.application.bot_data["db"].require().execute(
                """INSERT INTO file_settings(clone_id,setting_key,setting_value)
                   VALUES($1,'auto_delete',$2)
                   ON CONFLICT(clone_id,setting_key)
                   DO UPDATE SET setting_value=EXCLUDED.setting_value,updated_at=NOW()""",
                context.application.bot_data["clone_id"], str(seconds),
            )
            body = f"Auto-delete set to {seconds} seconds."
    await _reply(context, update, body)

async def storagehealth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context):
        return
    channel_id = context.application.bot_data.get("storage_channel_id")
    if not channel_id:
        body = "STORAGE_CHANNEL_ID is not configured."
    else:
        try:
            chat = await context.bot.get_chat(channel_id)
            bot_user = await context.bot.get_me()
            member = await context.bot.get_chat_member(channel_id, bot_user.id)
            can_post = getattr(member, "can_post_messages", None)
            body = (
                f"Storage channel reachable: {chat.title} ({channel_id}).\n"
                f"Bot membership: {member.status}.\n"
                f"Posting permission: {can_post if can_post is not None else 'not exposed'}."
            )
        except Exception as exc:
            body = f"Storage channel check failed: {type(exc).__name__}. Verify the bot's membership and channel ID."
    await _reply(context, update, body)

async def regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context):
        return
    if not context.args or not context.args[0].isdigit():
        body = "Usage: /regenerate SHARE_LINK_ID"
    else:
        link_id = int(context.args[0])
        token = secrets.token_urlsafe(12)
        row = await context.application.bot_data["db"].require().fetchrow(
            """UPDATE file_share_links SET token=$1
               WHERE id=$2 AND clone_id=$3 AND is_active=TRUE RETURNING token""",
            token, link_id, context.application.bot_data["clone_id"],
        )
        if row:
            me = await context.bot.get_me()
            body = f"New link: https://t.me/{me.username}?start={token}"
        else:
            body = "Active share-link record not found."
    await _reply(context, update, body)

async def setmaxfiles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update, context):
        return
    data = context.application.bot_data
    db = data["db"]
    clone_id = data["clone_id"]
    args = context.args
    if len(args) == 1 and args[0].isdigit():
        limit = int(args[0])
        if limit < 1 or limit > 10000:
            body = "The default file limit must be between 1 and 10000."
        else:
            data["max_files_per_user"] = limit
            await db.require().execute(
                """INSERT INTO file_settings(clone_id,setting_key,setting_value)
                   VALUES($1,'max_files_per_user',$2)
                   ON CONFLICT(clone_id,setting_key)
                   DO UPDATE SET setting_value=EXCLUDED.setting_value,updated_at=NOW()""",
                clone_id, str(limit),
            )
            body = f"Default per-request file limit set to {limit}."
    elif len(args) == 2 and args[0].lower() == "reset" and args[1].isdigit():
        user_id = int(args[1])
        await db.require().execute(
            """UPDATE bot_users SET max_files_per_request=NULL WHERE clone_id=$1 AND user_id=$2""",
            clone_id, user_id,
        )
        body = f"Custom file limit removed for user {user_id}. The default limit now applies."
    elif len(args) == 2 and args[0].isdigit() and args[1].isdigit():
        user_id, limit = int(args[0]), int(args[1])
        if limit < 1 or limit > 10000:
            body = "The individual file limit must be between 1 and 10000."
        else:
            await db.require().execute(
                """INSERT INTO bot_users(clone_id,user_id,max_files_per_request) VALUES($1,$2,$3)
                   ON CONFLICT(clone_id,user_id)
                   DO UPDATE SET max_files_per_request=EXCLUDED.max_files_per_request""",
                clone_id, user_id, limit,
            )
            body = f"Per-request file limit for user {user_id} set to {limit}."
    else:
        body = (
            "Usage:\n/setmaxfiles LIMIT\n/setmaxfiles USER_ID LIMIT\n"
            "/setmaxfiles reset USER_ID"
        )
    await _reply(context, update, body)

async def stream_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(
        context, update,
        "Direct HTTP streaming is not enabled in this build. It requires the streaming web module and domain configuration.",
    )

def add_file_handlers(app):
    app.add_handler(CommandHandler("genlink", genlink))
    app.add_handler(CommandHandler("batch", batch))
    app.add_handler(CommandHandler("collections", collections))
    app.add_handler(CommandHandler("collection", collection))
    app.add_handler(CommandHandler("delivery_stats", delivery_stats))
    app.add_handler(CommandHandler("dlt_time", dlt_time))
    app.add_handler(CommandHandler("storagehealth", storagehealth))
    app.add_handler(CommandHandler("regenerate", regenerate))
    app.add_handler(CommandHandler("setmaxfiles", setmaxfiles))
    app.add_handler(CommandHandler("link", stream_link))
    app.add_handler(CommandHandler("start", deliver), group=1)
