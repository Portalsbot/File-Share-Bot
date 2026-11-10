# File Sharing Bot — private project foundation

This repository contains the independently deployable File Sharing Bot foundation. It is **not yet the complete production feature set** from the command specification. The implemented foundation includes Telegram polling, PostgreSQL persistence, branded photo-caption responses, small-cap/custom-markup rendering, Start/About/Help navigation, message/button editing, single and batch share-link records, Telegram message copying, per-file Close controls, auto-delete, collection listing, delivery analytics, storage reachability checks and Owner-managed per-request file limits.

## Branding and navigation

Every bot-authored text response is sent with the configured branding image and its own permanent Close button. Each individually copied media message also receives its own Close button. Telegram does not allow an independent branding photo to be attached to a document, audio or video message, so file delivery uses a branded photo header followed by individually closable media messages.

The default direct image URL is:

https://i.ibb.co/PGpMYwYY/Gemini-Generated-Image-a7tjlia7tjlia7tj.png

The original GitHub blob page is not a direct image URL. The configured BRANDING_IMAGE_URL is used by default. Set BRANDING_IMAGE_PATH only when you intentionally want to use a local JPEG instead.

The Start screen includes About and Help navigation plus an optional Channel button. About and Help include a Back action to return to Start. Set CHANNEL_URL to the real public Telegram channel URL; if it is blank, the Channel button is omitted rather than pointing to a dummy destination.

Telegram photo captions are limited to 1024 characters after entity parsing. Long bot text is split into multiple branded photo-caption messages, each with its own Close button.

## Requirements

- Python 3.11+ (Docker image uses Python 3.12)
- PostgreSQL
- A Telegram bot token
- An official storage channel accessible to the bot, with the source messages stored there

## Run locally

~~~bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
# Edit .env, then:
python -m file_sharing_bot.main
~~~

## Implemented commands

| Command | Use |
|---|---|
| /start [share_token] | Open the welcome screen or access a file-share link |
| /upload | Start a persistent Owner/Admin upload session (up to 100 files) |
| /finish | Finish the current upload session and create its permanent access link |
| /help | Show Help with Start navigation |
| /about | Show About with Start navigation |
| /ping | Check whether the bot responds |
| /settings | Show the authorized management settings overview |
| /genlink CHANNEL_ID MESSAGE_ID | Create one-file link from the configured storage channel |
| /batch CHANNEL_ID FIRST_ID LAST_ID | Create a range link (up to 100 messages) |
| /collections | List existing File Collections (admin) |
| /collection COLLECTION_ID | View one File Collection and its existing public links (admin) |
| /newcollection TITLE | Create a File Collection |
| /addtocollection COLLECTION_ID SHARE_LINK_ID | Attach an existing share link |
| /removefromcollection COLLECTION_ID SHARE_LINK_ID | Remove an existing share link |
| /editcollection COLLECTION_ID NEW TITLE | Rename a File Collection |
| /deletecollection COLLECTION_ID | Delete a File Collection without deleting its links |
| /collectionpolicy COLLECTION_ID ... | Enforce per-collection file limits, user allow/deny lists and expiry |
| /linkscollection | Owner-only dashboard for permanent indexes of existing public links |
| /users, /userinfo USER_ID | View registered users and account status |
| /blockuser USER_ID, /unblockuser USER_ID | Restrict or restore a user |
| /bulkmaxfiles LIMIT USER_ID ... | Set limits for up to 200 users |
| /recover [USER_ID] | List or finalize interrupted upload sessions |
| /orphans | Explain storage-channel orphan-scan limitation |
| /broadcast, /broadcasts, /cancelbroadcast ID | Create, schedule and manage broadcasts |
| /setbackupchannel CHANNEL_ID | Configure the Telegram backup channel |
| /backup, /backups, /restore ID CONFIRM | Back up and restore bot data |
| /exportdata, /importdata | Export or import a validated JSON backup |
| /delivery_stats | View delivery outcomes (admin) |
| /dlt_time SECONDS | Configure delivery auto-delete (admin) |
| /setstoragechannel CHANNEL_ID | Configure central storage channel (Owner only) |
| /storagehealth | Check central channel reachability and bot membership (admin) |
| /regenerate SHARE_LINK_ID | Replace an active share token (admin) |
| /bulkregenerate SHARE_LINK_ID ... | Replace up to 100 active share tokens (admin) |
| /setmaxfiles LIMIT | Change the default per-request file limit (Owner only) |
| /setmaxfiles USER_ID LIMIT | Set one user's per-request override (Owner only) |
| /setmaxfiles reset USER_ID | Remove one user's override (Owner only) |
| /link | Report direct-streaming module status |
| /texts | List editable message templates (Owner only) |
| /edittext KEY | Edit one message template (Owner only) |
| /previewtext KEY | Preview a message template (Owner only) |
| /resettext KEY | Restore a default text template (Owner only) |
| /buttons KEY | Inspect template buttons (Owner only) |
| /addbutton KEY \| LABEL \| URL | Add an HTTP(S) URL button (Owner only) |
| /editbutton KEY \| INDEX \| LABEL \| URL | Edit a URL button (1-based; Owner only) |
| /delbutton KEY \| INDEX | Remove a URL button (1-based; Owner only) |

## Custom formatting

The formatter supports B, I, U, S, CODE, PRE, Q, SPOILER and HTTP(S) LINK blocks. Text outside code/pre is converted to the configured Unicode small-caps style. URLs, IDs and code snippets remain literal.

## Storage and access safeguards

- Link creation is restricted to the configured STORAGE_CHANNEL_ID; the bot will not create share links from arbitrary channels.
- Deep-link access checks the user's blocked status and the effective per-request file limit.
- Each copied file has its own Close button. When auto-delete is enabled, each delivered file is scheduled for individual deletion.
- Collection listing and detail commands require Owner/Admin access.
- /setmaxfiles is Owner-only and supports a global limit plus per-user overrides.

## Current implemented management features

- File Collections support creation, rename, deletion, adding/removing existing share-link IDs, and viewing their existing public links.
- `/collectionpolicy` enforces per-collection maximum file counts, allowed-user lists, blocked-user lists, disable switches and expiry timestamps during delivery.
- `/linkscollection` is an Owner-only persistent index of existing share links. Deleting an index does not delete the original links.
- User management includes listing, inspection, block/unblock and bulk per-user file limits.
- `/recover` lists and finalizes interrupted upload sessions. `/orphans` explains the storage scan limitation rather than pretending it can inspect channel history.
- Text/media broadcasts support URL buttons, immediate delivery, durable scheduled delivery, reports and cancellation.
- Telegram-channel backups, JSON export/import and Owner-confirmed restore are implemented. Configure `/setbackupchannel` before relying on remote backups.
- Admin command menus are published automatically when the bot starts. The HTTP health endpoint is `/health` when a `PORT` environment variable is supplied.

## Known limitations requiring your environment

Telegram Bot API does not provide channel-history enumeration. A complete orphan scan requires a separately configured MTProto client or an external storage index; do not share a Telegram user session string in chat. Direct HTTP streaming is not enabled in this build. Backups are limited by Telegram's document upload/download limits and should be complemented by PostgreSQL-native backups for large databases.

## License integration note

Before upstream code is copied into this private repository, retain source notices and comply with each upstream project's actual LICENSE file. Review GPL/Apache obligations separately. This scaffold does not copy third-party source files wholesale.
\n## Upload workflow\n\n- `/upload` starts a persistent Owner/Admin upload session and copies each received file into the configured storage channel.\n- Send up to 100 supported media messages, then use `/finish` to create one permanent File Sharing Bot deep link for the uploaded set.\n- The upload session is stored in PostgreSQL, so the session record survives a bot restart. Use the inline Cancel button to abandon the session.\n- The bot must be an administrator in the storage channel with permission to post messages.\n

## Collections

- `/newcollection TITLE` creates a File Collection.
- `/addtocollection COLLECTION_ID SHARE_LINK_ID` and `/removefromcollection COLLECTION_ID SHARE_LINK_ID` manage references to existing share links.
- `/editcollection COLLECTION_ID NEW TITLE` renames a collection; `/deletecollection COLLECTION_ID` deletes only the collection record, not the underlying share links.
- `/linkscollection` opens the Owner-only dashboard for permanent named collections of existing public share links. Its Add flow accepts `COLLECTION NAME | SHARE_LINK_ID SHARE_LINK_ID ...`. The All Collections view opens the saved public links; deleting a Link Collection never deletes the underlying share links.

## Web-service health check

When deploying as a web service, the platform-provided `PORT` variable starts a lightweight HTTP server. Configure the platform health-check path as `/health`. This endpoint reports process liveness; it does not prove Telegram or PostgreSQL connectivity. Use `/storagehealth` and `/ping` inside Telegram for those checks.

Broadcast text can include one URL button per line using `[button] LABEL | https://URL`. The bot shows a preview before immediate or scheduled delivery.

## Force-subscription management

Use `/fsubs` as Owner/Admin. The panel provides **Add**, **Remove**, **Edit Message**, **Back** and **Close**. Add accepts a numeric Telegram channel ID and verifies bot-admin permissions. Remove displays active FSub channels as individual buttons. Edit changes the user-facing message displayed only to users who have not joined. Owner/Admin accounts bypass FSub checks. A user who opens a file deep link is returned to that exact file delivery after completing the membership check.
