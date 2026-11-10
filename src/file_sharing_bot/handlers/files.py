from __future__ import annotations
import logging
import json
import secrets
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import MessageHandler, CallbackQueryHandler, filters
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



async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context):
        return
    storage_id = context.application.bot_data.get("storage_channel_id")
    if not storage_id:
        await _reply(context, update, "STORAGE_CHANNEL_ID is not configured. Upload mode is unavailable.")
        return
    try:
        chat = await context.bot.get_chat(storage_id)
        me = await context.bot.get_me()
        member = await context.bot.get_chat_member(storage_id, me.id)
        if getattr(member, "status", None) not in {"administrator", "creator"}:
            raise RuntimeError("The bot is not an administrator in the storage channel.")
        if getattr(member, "can_post_messages", True) is False:
            raise RuntimeError("The bot cannot post messages in the storage channel.")
    except Exception as exc:
        await _reply(context, update, f"Storage channel is not ready: {type(exc).__name__}. Check bot admin/post permissions.")
        return
    db = context.application.bot_data["db"]
    existing = await db.require().fetchrow(
        """SELECT cardinality(message_ids) AS file_count FROM file_upload_sessions
           WHERE clone_id=$1 AND user_id=$2 AND active=TRUE""",
        context.application.bot_data["clone_id"], update.effective_user.id)
    if existing and int(existing["file_count"] or 0) > 0:
        await _reply(context, update,
            f"You already have an active upload session with {existing['file_count']} files. Use /finish to create its link or Cancel to abandon it before starting another.")
        return
    await db.require().execute(
        """INSERT INTO file_upload_sessions(clone_id,user_id,source_chat_id,message_ids,active)
           VALUES($1,$2,$3,'{}',TRUE)
           ON CONFLICT(clone_id,user_id) DO UPDATE SET source_chat_id=EXCLUDED.source_chat_id,
           message_ids='{}',active=TRUE,created_at=NOW(),updated_at=NOW()""",
        context.application.bot_data["clone_id"], update.effective_user.id, storage_id)
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("· ᴄᴀɴᴄᴇʟ ᴜᴘʟᴏᴀᴅ ·", callback_data="upload:cancel")]])
    await _reply(context, update,
        f"Upload session started for {chat.title or storage_id}. Send up to 100 files here, then use /finish to create one permanent access link.", markup)


async def collect_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not _is_admin(update, context):
        return
    if context.user_data.pop("suppress_upload_once", False):
        return
    attachment = (message.document or message.video or message.audio or message.animation
                  or message.voice or message.video_note or message.sticker or message.photo)
    db = context.application.bot_data["db"]
    clone_id = context.application.bot_data["clone_id"]
    pool = db.require()
    copied = None
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                session = await conn.fetchrow(
                    """SELECT source_chat_id,message_ids FROM file_upload_sessions
                       WHERE clone_id=$1 AND user_id=$2 AND active=TRUE FOR UPDATE""",
                    clone_id, user.id)
                if not session:
                    return
                current_ids = list(session["message_ids"] or [])
                if not attachment:
                    await _reply(context, update, "Please send a document, photo, video, audio or supported Telegram media file. Use /finish when complete.")
                    return
                if len(current_ids) >= 100:
                    await _reply(context, update, "This upload session has reached its 100-file limit. Use /finish to create the link.")
                    return
                copied = await context.bot.copy_message(
                    chat_id=session["source_chat_id"], from_chat_id=message.chat_id,
                    message_id=message.message_id, protect_content=False)
                await conn.execute(
                    """UPDATE file_upload_sessions SET message_ids=array_append(message_ids,$3),updated_at=NOW()
                       WHERE clone_id=$1 AND user_id=$2 AND active=TRUE""",
                    clone_id, user.id, copied.message_id)
                count = len(current_ids) + 1
        await _reply(context, update, f"Added file {count}/100. Send another file or use /finish.")
    except Exception as exc:
        if copied is not None:
            try:
                await context.bot.delete_message(chat_id=context.application.bot_data["storage_channel_id"], message_id=copied.message_id)
            except Exception:
                log.warning("Could not remove untracked upload copy after database failure")
        log.exception("Upload collection failed")
        await _reply(context, update, f"Could not add this file: {type(exc).__name__}. Your existing session remains available.")


async def finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context):
        return
    db = context.application.bot_data["db"]
    clone_id = context.application.bot_data["clone_id"]
    async with db.require().acquire() as conn:
        async with conn.transaction():
            session = await conn.fetchrow(
                """SELECT source_chat_id,message_ids FROM file_upload_sessions
                   WHERE clone_id=$1 AND user_id=$2 AND active=TRUE FOR UPDATE""",
                clone_id, update.effective_user.id)
            if not session:
                body = "There is no active upload session. Use /upload first."
            else:
                message_ids = list(session["message_ids"] or [])
                if not message_ids:
                    body = "No files have been added yet. Send files before using /finish."
                else:
                    token = secrets.token_urlsafe(12)
                    await conn.execute(
                        """INSERT INTO file_share_links(clone_id,token,source_chat_id,message_ids,created_by)
                           VALUES($1,$2,$3,$4,$5)""",
                        clone_id, token, session["source_chat_id"], message_ids, update.effective_user.id)
                    await conn.execute(
                        """UPDATE file_upload_sessions SET active=FALSE,updated_at=NOW()
                           WHERE clone_id=$1 AND user_id=$2""", clone_id, update.effective_user.id)
                    me = await context.bot.get_me()
                    body = f"Upload completed: {len(message_ids)} files saved.\nPermanent access link:\nhttps://t.me/{me.username}?start={token}"
    await _reply(context, update, body)


async def cancel_upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    user_id = query.from_user.id
    if user_id != context.application.bot_data["owner_id"] and user_id not in context.application.bot_data["admins"]:
        await query.answer("Owner / Admin only.", show_alert=True)
        return
    await context.application.bot_data["db"].require().execute(
        """UPDATE file_upload_sessions SET active=FALSE,updated_at=NOW()
           WHERE clone_id=$1 AND user_id=$2 AND active=TRUE""",
        context.application.bot_data["clone_id"], user_id)
    await query.answer("Upload session cancelled.")
    try:
        await query.message.delete()
    except Exception:
        pass

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

async def _collection_policy_for_link(context, link_id: int, user_id: int):
    rows = await context.application.bot_data["db"].require().fetch(
        """SELECT collection_key,title,metadata FROM file_collections
           WHERE clone_id=$1 AND metadata->'link_ids' @> jsonb_build_array($2::bigint)""",
        context.application.bot_data["clone_id"], link_id)
    limit = None
    for row in rows:
        metadata = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
        policy = metadata.get("policy", {})
        if policy.get("disabled"):
            return None, f"Collection {row['collection_key']} is currently disabled."
        allowed = {int(value) for value in policy.get("allowed_users", [])}
        blocked = {int(value) for value in policy.get("blocked_users", [])}
        if allowed and user_id not in allowed:
            return None, f"Your account is not allowed to access collection {row['title']}."
        if user_id in blocked:
            return None, f"Your account is blocked from collection {row['title']}."
        expires_at = policy.get("expires_at")
        if expires_at:
            try:
                expiry = datetime.fromisoformat(expires_at)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= datetime.now(timezone.utc):
                    return None, f"Collection {row['title']} has expired."
            except ValueError:
                return None, f"Collection {row['title']} has an invalid expiry policy. Contact the owner."
        if policy.get("max_files_per_request") is not None:
            value = int(policy["max_files_per_request"])
            limit = value if limit is None else min(limit, value)
    return limit, None


async def collectionpolicy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    if not context.args:
        body = "Usage: /collectionpolicy COLLECTION_ID [maxfiles=N allowed=ID,ID blocked=ID,ID expires=ISO_TIME | clear]"
    else:
        key = context.args[0]
        db = context.application.bot_data["db"].require()
        row = await db.fetchrow(
            "SELECT metadata,title FROM file_collections WHERE clone_id=$1 AND collection_key=$2",
            context.application.bot_data["clone_id"], key)
        if not row:
            body = "File Collection not found."
        else:
            metadata = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
            if len(context.args) == 1:
                body = f"Policy for {row['title']}: {json.dumps(metadata.get('policy', {}), ensure_ascii=False) or 'none'}"
            elif context.args[1].lower() == "clear" and len(context.args) == 2:
                metadata.pop("policy", None)
                await db.execute("UPDATE file_collections SET metadata=$1::jsonb WHERE clone_id=$2 AND collection_key=$3",
                                 json.dumps(metadata), context.application.bot_data["clone_id"], key)
                body = f"Access policy cleared for {key}."
            else:
                policy = dict(metadata.get("policy", {}))
                try:
                    for item in context.args[1:]:
                        if "=" not in item: raise ValueError(f"Invalid option: {item}")
                        name, value = item.split("=", 1)
                        if name == "maxfiles":
                            number = int(value)
                            if number < 1 or number > 10000: raise ValueError("maxfiles must be 1–10000")
                            policy["max_files_per_request"] = number
                        elif name in {"allowed", "blocked"}:
                            ids = [int(x) for x in value.split(",") if x]
                            if len(ids) > 200 or any(x <= 0 for x in ids): raise ValueError(f"{name} accepts up to 200 positive user IDs")
                            policy["allowed_users" if name == "allowed" else "blocked_users"] = ids
                        elif name == "expires":
                            expiry = datetime.fromisoformat(value)
                            if expiry.tzinfo is None: raise ValueError("expires must include a timezone offset")
                            policy["expires_at"] = expiry.isoformat()
                        elif name == "disabled":
                            if value.lower() not in {"true", "false"}: raise ValueError("disabled must be true or false")
                            policy["disabled"] = value.lower() == "true"
                        else:
                            raise ValueError(f"Unknown policy option: {name}")
                    metadata["policy"] = policy
                    await db.execute("UPDATE file_collections SET metadata=$1::jsonb WHERE clone_id=$2 AND collection_key=$3",
                                     json.dumps(metadata), context.application.bot_data["clone_id"], key)
                    body = f"Access policy updated for {key}: {json.dumps(policy, ensure_ascii=False)}"
                except Exception as exc:
                    body = f"Policy not changed: {str(exc)[:160]}"
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
    collection_limit, policy_error = await _collection_policy_for_link(context, int(row["id"]), user_id)
    if policy_error:
        await _reply(context, update, policy_error)
        await db.require().execute(
            "INSERT INTO file_delivery_events(clone_id,token,user_id,status,detail) VALUES($1,$2,$3,'failed',$4)",
            clone_id, token, user_id, "collection_policy_denied")
        return
    if collection_limit is not None:
        per_user_limit = min(per_user_limit, collection_limit)
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

    success = 0
    for index, message_id in enumerate(message_ids, start=1):
        try:
            # Telegram cannot attach a separate branding photo to copyMessage.
            # Send an individually closable branded header immediately before each file.
            await _reply(context, update, f"ᴅᴇʟɪᴠᴇʀɪɴɢ ғɪʟᴇ {index}/{len(message_ids)}.")
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
            metadata = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
            ids = [int(value) for value in metadata.get("link_ids", [])]
            records = await context.application.bot_data["db"].require().fetch(
                "SELECT id,token FROM file_share_links WHERE clone_id=$1 AND id=ANY($2::bigint[]) AND is_active=TRUE ORDER BY id",
                context.application.bot_data["clone_id"], ids)
            me = await context.bot.get_me()
            links_text = "\n".join(f"#{item['id']} · https://t.me/{me.username}?start={item['token']}" for item in records)
            body = (
                f"**{row['title']}**\nID: {row['collection_key']}\n"
                f"Created: {row['created_at']}\nActive links: {len(records)}\n\n{links_text or 'No active share links attached.'}"
            )
        else:
            body = "Collection not found."
    await _reply(context, update, body)

async def newcollection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    title = " ".join(context.args).strip()
    if not title:
        body = "Usage: /newcollection COLLECTION NAME"
    else:
        key = "COL-" + secrets.token_hex(3).upper()
        await context.application.bot_data["db"].require().execute(
            "INSERT INTO file_collections(clone_id,collection_key,title) VALUES($1,$2,$3)",
            context.application.bot_data["clone_id"], key, title)
        body = f"File Collection created. ID: {key} · {title}\nAdd existing share-link IDs with /addtocollection {key} LINK_ID."
    await _reply(context, update, body)


async def addtocollection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    if len(context.args) != 2 or not context.args[1].isdigit():
        body = "Usage: /addtocollection COLLECTION_ID SHARE_LINK_ID"
    else:
        db = context.application.bot_data["db"].require()
        clone_id, key, link_id = context.application.bot_data["clone_id"], context.args[0], int(context.args[1])
        link = await db.fetchrow("SELECT id FROM file_share_links WHERE clone_id=$1 AND id=$2 AND is_active=TRUE", clone_id, link_id)
        row = await db.fetchrow("SELECT metadata FROM file_collections WHERE clone_id=$1 AND collection_key=$2", clone_id, key)
        if not row: body = "File Collection not found."
        elif not link: body = "Active share link not found."
        else:
            metadata = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
            ids = list(dict.fromkeys([int(x) for x in metadata.get("link_ids", [])] + [link_id]))
            metadata["link_ids"] = ids
            await db.execute("UPDATE file_collections SET metadata=$1::jsonb WHERE clone_id=$2 AND collection_key=$3",
                             json.dumps(metadata), clone_id, key)
            body = f"Share link #{link_id} added to {key}. Total links: {len(ids)}."
    await _reply(context, update, body)


async def removefromcollection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    if len(context.args) != 2 or not context.args[1].isdigit():
        body = "Usage: /removefromcollection COLLECTION_ID SHARE_LINK_ID"
    else:
        db = context.application.bot_data["db"].require()
        key, link_id = context.args[0], int(context.args[1])
        row = await db.fetchrow("SELECT metadata FROM file_collections WHERE clone_id=$1 AND collection_key=$2",
                                context.application.bot_data["clone_id"], key)
        if not row: body = "File Collection not found."
        else:
            metadata = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
            ids = [int(x) for x in metadata.get("link_ids", []) if int(x) != link_id]
            metadata["link_ids"] = ids
            await db.execute("UPDATE file_collections SET metadata=$1::jsonb WHERE clone_id=$2 AND collection_key=$3",
                             json.dumps(metadata), context.application.bot_data["clone_id"], key)
            body = f"Share link #{link_id} removed from {key}."
    await _reply(context, update, body)


async def editcollection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    if len(context.args) < 2:
        body = "Usage: /editcollection COLLECTION_ID NEW NAME"
    else:
        key, title = context.args[0], " ".join(context.args[1:])
        result = await context.application.bot_data["db"].require().execute(
            "UPDATE file_collections SET title=$1 WHERE clone_id=$2 AND collection_key=$3",
            title, context.application.bot_data["clone_id"], key)
        body = "Collection name updated." if result.endswith("1") else "Collection not found."
    await _reply(context, update, body)


async def deletecollection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    if len(context.args) != 1:
        body = "Usage: /deletecollection COLLECTION_ID"
    else:
        result = await context.application.bot_data["db"].require().execute(
            "DELETE FROM file_collections WHERE clone_id=$1 AND collection_key=$2",
            context.application.bot_data["clone_id"], context.args[0])
        body = "File Collection deleted. Its original share links remain active." if result.endswith("1") else "Collection not found."
    await _reply(context, update, body)


async def link_collection_view(update: Update, context: ContextTypes.DEFAULT_TYPE, collection_id: int):
    db = context.application.bot_data["db"].require()
    row = await db.fetchrow("SELECT title,link_ids FROM file_link_collections WHERE clone_id=$1 AND id=$2",
                            context.application.bot_data["clone_id"], collection_id)
    if not row:
        body = "Link Collection not found."
    else:
        ids = list(row["link_ids"] or [])
        records = await db.fetch(
            "SELECT id,token FROM file_share_links WHERE clone_id=$1 AND id=ANY($2::bigint[]) AND is_active=TRUE ORDER BY id",
            context.application.bot_data["clone_id"], ids)
        me = await context.bot.get_me()
        body = f"**{row['title']}** · {len(records)} active links\n\n" + (
            "\n".join(f"Link #{item['id']}: https://t.me/{me.username}?start={item['token']}" for item in records)
            if records else "No active share links are attached.")
    await _reply(context, update, body)


async def linkscollection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update, context): return
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("· ᴀᴅᴅ ·", callback_data="linkcol:add"),
         InlineKeyboardButton("· ᴅᴇʟᴇᴛᴇ ·", callback_data="linkcol:delete")],
        [InlineKeyboardButton("· ᴀʟʟ ᴄᴏʟʟᴇᴄᴛɪᴏɴs ·", callback_data="linkcol:all")],
    ])
    await _reply(context, update, "Manage your permanent index of existing public file-share links.", markup)


async def link_collection_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update, context) or context.user_data.get("link_collection_action") != "add":
        return
    context.user_data.pop("link_collection_action", None)
    context.user_data["suppress_upload_once"] = True
    raw = (update.effective_message.text or "").strip()
    if "|" not in raw:
        await _reply(context, update, "Format: COLLECTION NAME | SHARE_LINK_ID SHARE_LINK_ID ...")
        return
    title, raw_ids = [part.strip() for part in raw.split("|", 1)]
    try:
        ids = list(dict.fromkeys(int(x) for x in raw_ids.split()))
        if not title or not ids or len(ids) > 100 or any(x <= 0 for x in ids):
            raise ValueError
        rows = await context.application.bot_data["db"].require().fetch(
            "SELECT id FROM file_share_links WHERE clone_id=$1 AND id=ANY($2::bigint[]) AND is_active=TRUE",
            context.application.bot_data["clone_id"], ids)
        valid = {int(row["id"]) for row in rows}
        if valid != set(ids):
            raise ValueError("One or more share-link IDs do not exist or are inactive.")
        key = "LNK-" + secrets.token_hex(3).upper()
        await context.application.bot_data["db"].require().execute(
            "INSERT INTO file_link_collections(clone_id,collection_key,title,link_ids,created_by) VALUES($1,$2,$3,$4,$5)",
            context.application.bot_data["clone_id"], key, title, ids, update.effective_user.id)
        await _reply(context, update, f"Link Collection created: {title} · {key} · {len(ids)} existing links indexed.")
    except Exception as exc:
        await _reply(context, update, f"Could not create Link Collection: {str(exc)[:160]}")


async def link_collection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query: return
    if query.from_user.id != context.application.bot_data["owner_id"]:
        await query.answer("Owner only.", show_alert=True)
        return
    await query.answer()
    action = query.data.split(":")
    if action[1] == "add":
        context.user_data["link_collection_action"] = "add"
        await send_branded(context.bot, query.message.chat_id,
            "Send: COLLECTION NAME | SHARE_LINK_ID SHARE_LINK_ID ...\nExample: Naruto Season 1 | 12 13 14",
            image_url=context.application.bot_data["image_url"],
            image_path=context.application.bot_data["image_path"],
            small_caps=context.application.bot_data["small_caps"])
    elif action[1] == "all":
        rows = await context.application.bot_data["db"].require().fetch(
            "SELECT id,title,collection_key,cardinality(link_ids) AS count FROM file_link_collections WHERE clone_id=$1 ORDER BY id DESC LIMIT 50",
            context.application.bot_data["clone_id"])
        buttons = [[InlineKeyboardButton(f"{row['title']} · {row['count']} links", callback_data=f"linkcol:view:{row['id']}")]
                   for row in rows]
        await send_branded(context.bot, query.message.chat_id,
            "All Link Collections:" if rows else "No Link Collections have been created.",
            image_url=context.application.bot_data["image_url"], image_path=context.application.bot_data["image_path"],
            small_caps=context.application.bot_data["small_caps"],
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)
    elif action[1] == "delete":
        rows = await context.application.bot_data["db"].require().fetch(
            "SELECT id,title FROM file_link_collections WHERE clone_id=$1 ORDER BY id DESC LIMIT 50",
            context.application.bot_data["clone_id"])
        buttons = [[InlineKeyboardButton(f"· {row['title']} ·", callback_data=f"linkcol:del:{row['id']}")]
                   for row in rows]
        await send_branded(context.bot, query.message.chat_id,
            "Choose a Link Collection to delete:" if rows else "No Link Collections to delete.",
            image_url=context.application.bot_data["image_url"], image_path=context.application.bot_data["image_path"],
            small_caps=context.application.bot_data["small_caps"],
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)
    elif action[1] == "view" and len(action) == 3 and action[2].isdigit():
        await link_collection_view(update, context, int(action[2]))
    elif action[1] == "del" and len(action) == 3 and action[2].isdigit():
        result = await context.application.bot_data["db"].require().execute(
            "DELETE FROM file_link_collections WHERE clone_id=$1 AND id=$2",
            context.application.bot_data["clone_id"], int(action[2]))
        await send_branded(context.bot, query.message.chat_id,
            "Link Collection deleted. Original share links remain unchanged." if result.endswith("1") else "Collection not found.",
            image_url=context.application.bot_data["image_url"], image_path=context.application.bot_data["image_path"],
            small_caps=context.application.bot_data["small_caps"])


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

async def setstoragechannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update, context): return
    if len(context.args) != 1 or not context.args[0].lstrip("-").isdigit():
        body = "Usage: /setstoragechannel CHANNEL_ID"
    else:
        channel_id = int(context.args[0])
        try:
            chat = await context.bot.get_chat(channel_id)
            me = await context.bot.get_me()
            member = await context.bot.get_chat_member(channel_id, me.id)
            if getattr(member, "status", "") not in {"administrator", "creator"}:
                raise PermissionError("The bot must be an administrator in the storage channel.")
            if getattr(member, "can_post_messages", True) is False:
                raise PermissionError("The bot needs permission to post in the storage channel.")
            await context.application.bot_data["db"].require().execute(
                """INSERT INTO file_settings(clone_id,setting_key,setting_value)
                   VALUES($1,'storage_channel_id',$2)
                   ON CONFLICT(clone_id,setting_key)
                   DO UPDATE SET setting_value=EXCLUDED.setting_value,updated_at=NOW()""",
                context.application.bot_data["clone_id"], str(channel_id))
            context.application.bot_data["storage_channel_id"] = channel_id
            body = f"Storage channel configured: {chat.title or channel_id} ({channel_id})."
        except Exception as exc:
            body = f"Storage channel was not changed: {type(exc).__name__}: {str(exc)[:150]}"
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

async def bulkregenerate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    if not context.args or not all(value.isdigit() for value in context.args):
        body = "Usage: /bulkregenerate SHARE_LINK_ID SHARE_LINK_ID ..."
    else:
        ids = list(dict.fromkeys(int(value) for value in context.args))
        if len(ids) > 100:
            body = "A maximum of 100 share links can be regenerated per request."
        else:
            db = context.application.bot_data["db"].require()
            rows = await db.fetch(
                "SELECT id FROM file_share_links WHERE clone_id=$1 AND id=ANY($2::bigint[]) AND is_active=TRUE ORDER BY id",
                context.application.bot_data["clone_id"], ids)
            me = await context.bot.get_me()
            results = []
            for row in rows:
                token = secrets.token_urlsafe(12)
                await db.execute(
                    "UPDATE file_share_links SET token=$1 WHERE clone_id=$2 AND id=$3",
                    token, context.application.bot_data["clone_id"], row["id"])
                results.append(f"#{row['id']} · https://t.me/{me.username}?start={token}")
            body = f"Regenerated {len(results)} of {len(ids)} requested links. Old tokens are now invalid.\n\n" + ("\n".join(results) if results else "No active matching links.")
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

async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    db = context.application.bot_data["db"].require()
    clone_id = context.application.bot_data["clone_id"]
    total = await db.fetchval("SELECT COUNT(*) FROM bot_users WHERE clone_id=$1", clone_id)
    rows = await db.fetch(
        "SELECT user_id,is_banned,last_seen FROM bot_users WHERE clone_id=$1 ORDER BY last_seen DESC LIMIT 25",
        clone_id)
    body = f"**ᴜsᴇʀ ᴅᴀsʜʙᴏᴀʀᴅ** · Total: {total}\n\n" + (
        "\n".join(f"{row['user_id']} · {'blocked' if row['is_banned'] else 'active'} · {row['last_seen']}" for row in rows)
        if rows else "No registered users.")
    await _reply(context, update, body)


async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    if len(context.args) != 1 or not context.args[0].isdigit():
        body = "Usage: /userinfo USER_ID"
    else:
        row = await context.application.bot_data["db"].require().fetchrow(
            "SELECT user_id,first_seen,last_seen,is_banned,max_files_per_request FROM bot_users WHERE clone_id=$1 AND user_id=$2",
            context.application.bot_data["clone_id"], int(context.args[0]))
        body = (f"User: {row['user_id']}\nFirst seen: {row['first_seen']}\nLast seen: {row['last_seen']}\n"
                f"Blocked: {row['is_banned']}\nCustom file limit: {row['max_files_per_request'] or 'default'}") if row else "User not found."
    await _reply(context, update, body)


async def blockuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    if len(context.args) != 1 or not context.args[0].isdigit():
        body = "Usage: /blockuser USER_ID"
    else:
        result = await context.application.bot_data["db"].require().execute(
            "UPDATE bot_users SET is_banned=TRUE WHERE clone_id=$1 AND user_id=$2",
            context.application.bot_data["clone_id"], int(context.args[0]))
        body = "User blocked." if result.endswith("1") else "User not found."
    await _reply(context, update, body)


async def unblockuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    if len(context.args) != 1 or not context.args[0].isdigit():
        body = "Usage: /unblockuser USER_ID"
    else:
        result = await context.application.bot_data["db"].require().execute(
            "UPDATE bot_users SET is_banned=FALSE WHERE clone_id=$1 AND user_id=$2",
            context.application.bot_data["clone_id"], int(context.args[0]))
        body = "User unblocked." if result.endswith("1") else "User not found."
    await _reply(context, update, body)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    row = await context.application.bot_data["db"].require().fetchrow(
        """SELECT COUNT(*) total,COUNT(*) FILTER(WHERE is_banned=TRUE) blocked,
           COUNT(*) FILTER(WHERE last_seen>NOW()-INTERVAL '24 hours') active_24h
           FROM bot_users WHERE clone_id=$1""", context.application.bot_data["clone_id"])
    await _reply(context, update, f"**sᴛᴀᴛɪsᴛɪᴄs**\nUsers: {row['total']}\nBlocked: {row['blocked']}\nActive in 24h: {row['active_24h']}")


async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    rows = await context.application.bot_data["db"].require().fetch(
        """SELECT token,user_id,status,detail,created_at FROM file_delivery_events
           WHERE clone_id=$1 ORDER BY id DESC LIMIT 20""", context.application.bot_data["clone_id"])
    body = "**ʀᴇᴄᴇɴᴛ ᴅᴇʟɪᴠᴇʀʏ ʟᴏɢs**\n\n" + (
        "\n".join(f"{r['status']} · user {r['user_id']} · {r['detail'] or ''} · {r['created_at']}" for r in rows)
        if rows else "No delivery events.")
    await _reply(context, update, body)


async def bulkmaxfiles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update, context): return
    if len(context.args) < 2 or not context.args[0].isdigit() or not all(x.isdigit() for x in context.args[1:]):
        body = "Usage: /bulkmaxfiles LIMIT USER_ID USER_ID ..."
    else:
        limit = int(context.args[0])
        ids = list(dict.fromkeys(int(x) for x in context.args[1:]))
        if limit < 1 or limit > 10000 or len(ids) > 200:
            body = "Limit must be 1–10000 and at most 200 user IDs can be updated at once."
        else:
            for user_id in ids:
                await context.application.bot_data["db"].require().execute(
                    """INSERT INTO bot_users(clone_id,user_id,max_files_per_request) VALUES($1,$2,$3)
                       ON CONFLICT(clone_id,user_id) DO UPDATE SET max_files_per_request=EXCLUDED.max_files_per_request""",
                    context.application.bot_data["clone_id"], user_id, limit)
            body = f"Updated the per-request file limit to {limit} for {len(ids)} users."
    await _reply(context, update, body)


async def recover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    db = context.application.bot_data["db"].require()
    clone_id = context.application.bot_data["clone_id"]
    if not context.args:
        rows = await db.fetch(
            """SELECT user_id,cardinality(message_ids) AS file_count,updated_at FROM file_upload_sessions
               WHERE clone_id=$1 AND active=TRUE ORDER BY updated_at DESC LIMIT 30""", clone_id)
        body = "**ʀᴇᴄᴏᴠᴇʀᴀʙʟᴇ ᴜᴘʟᴏᴀᴅ sᴇssɪᴏɴs**\n\n" + (
            "\n".join(f"User {r['user_id']} · {r['file_count']} files · /recover {r['user_id']}" for r in rows)
            if rows else "No active upload sessions.")
    elif len(context.args) == 1 and context.args[0].isdigit():
        user_id = int(context.args[0])
        async with db.acquire() as conn:
            async with conn.transaction():
                session = await conn.fetchrow(
                    """SELECT source_chat_id,message_ids FROM file_upload_sessions
                       WHERE clone_id=$1 AND user_id=$2 AND active=TRUE FOR UPDATE""", clone_id, user_id)
                if not session or not session["message_ids"]:
                    body = "No recoverable files found for that user."
                else:
                    token = secrets.token_urlsafe(12)
                    ids = list(session["message_ids"])
                    await conn.execute(
                        """INSERT INTO file_share_links(clone_id,token,source_chat_id,message_ids,created_by)
                           VALUES($1,$2,$3,$4,$5)""", clone_id, token, session["source_chat_id"], ids, update.effective_user.id)
                    await conn.execute(
                        "UPDATE file_upload_sessions SET active=FALSE,updated_at=NOW() WHERE clone_id=$1 AND user_id=$2",
                        clone_id, user_id)
                    me = await context.bot.get_me()
                    body = f"Recovered {len(ids)} files from user {user_id}.\nhttps://t.me/{me.username}?start={token}"
    else:
        body = "Usage: /recover [USER_ID]"
    await _reply(context, update, body)


async def orphans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update, context): return
    body = ("Full orphan-file scanning is not available through Telegram Bot API: it cannot enumerate a channel's message history. "
            "The bot can recover active upload sessions with /recover, but a complete storage-channel scan requires an MTProto client or an external storage index.")
    await _reply(context, update, body)


async def stream_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(
        context, update,
        "Direct HTTP streaming is not enabled in this build. It requires the streaming web module and domain configuration.",
    )

def add_file_handlers(app):
    app.add_handler(CommandHandler("upload", upload))
    app.add_handler(CommandHandler("finish", finish))
    app.add_handler(CallbackQueryHandler(cancel_upload_callback, pattern=r"^upload:cancel$"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, collect_upload), group=2)
    app.add_handler(CommandHandler("genlink", genlink))
    app.add_handler(CommandHandler("batch", batch))
    app.add_handler(CommandHandler("collections", collections))
    app.add_handler(CommandHandler("collection", collection))
    app.add_handler(CommandHandler("collectionpolicy", collectionpolicy))
    app.add_handler(CommandHandler("newcollection", newcollection))
    app.add_handler(CommandHandler("addtocollection", addtocollection))
    app.add_handler(CommandHandler("removefromcollection", removefromcollection))
    app.add_handler(CommandHandler("editcollection", editcollection))
    app.add_handler(CommandHandler("deletecollection", deletecollection))
    app.add_handler(CommandHandler("linkscollection", linkscollection))
    app.add_handler(CallbackQueryHandler(link_collection_callback, pattern=r"^linkcol:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, link_collection_input), group=1)
    app.add_handler(CommandHandler("delivery_stats", delivery_stats))
    app.add_handler(CommandHandler("dlt_time", dlt_time))
    app.add_handler(CommandHandler("setstoragechannel", setstoragechannel))
    app.add_handler(CommandHandler("storagehealth", storagehealth))
    app.add_handler(CommandHandler("regenerate", regenerate))
    app.add_handler(CommandHandler("bulkregenerate", bulkregenerate))
    app.add_handler(CommandHandler("setmaxfiles", setmaxfiles))
    app.add_handler(CommandHandler("bulkmaxfiles", bulkmaxfiles))
    app.add_handler(CommandHandler("users", users))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("blockuser", blockuser))
    app.add_handler(CommandHandler("unblockuser", unblockuser))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("logs", logs))
    app.add_handler(CommandHandler("recover", recover))
    app.add_handler(CommandHandler("orphans", orphans))
    app.add_handler(CommandHandler("link", stream_link))
    app.add_handler(CommandHandler("start", deliver), group=1)
