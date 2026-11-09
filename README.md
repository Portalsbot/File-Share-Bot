# File Sharing Bot — private project foundation

This ZIP is the first independently deployable project foundation for the File Sharing Bot master repository. It is **not yet the complete production feature set** described in the product specification. The current code includes a working Telegram application shell, PostgreSQL persistence, small-caps/custom-markup rendering, branded photo-caption replies, message/button editing, single/batch share-link records, Telegram message copying, basic auto-delete, collection listing, delivery analytics, and storage reachability checks.

## Branding image

Every bot-authored text response is sent as a photo with a caption. The default is the direct raw image URL:

`https://raw.githubusercontent.com/Portalsbot/image/main/photo_2026-11-01_20-42-48.jpg`

Original link supplied: `https://github.com/Portalsbot/image/blob/main/photo_2026-11-01_20-42-48.jpg`. The GitHub `blob` page is not an image-file URL, so the application uses the corresponding `raw.githubusercontent.com` URL. The image file was not bundled because this build environment could not download external binary content; verify that the repository is public and that Telegram can fetch the raw URL. A local image can be mounted and configured with `BRANDING_IMAGE_PATH`.

Telegram photo captions are limited to 1024 characters after entity parsing. Long bot text is split into multiple branded photo-caption messages. **Media delivered as files/videos/audio remains separate Telegram media messages**; Telegram cannot attach an independent branding photo to the same document/audio message.

## Requirements

- Python 3.11+ (Docker image uses Python 3.12)
- PostgreSQL
- A Telegram bot token
- An official storage channel accessible to the bot, with the source messages stored there

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
# Edit .env, then:
python -m file_sharing_bot.main
```

## Included commands

| Command | Use |
|---|---|
| `/start [share_token]` | Start or access a file share link |
| `/help` | Show commands |
| `/about` | Show bot information |
| `/ping` | Health response |
| `/settings` | Settings overview |
| `/genlink CHANNEL_ID MESSAGE_ID` | Create a link for one stored message |
| `/batch CHANNEL_ID FIRST_ID LAST_ID` | Create a range link (up to 100 messages) |
| `/collections` | List collections |
| `/collection COLLECTION_ID` | View collection metadata |
| `/delivery_stats` | Delivery outcomes (admin) |
| `/dlt_time SECONDS` | Configure auto-delete (admin) |
| `/storagehealth` | Check central channel reachability (admin) |
| `/regenerate SHARE_LINK_ID` | Replace a share token (admin) |
| `/link` | Explains direct-streaming module status |
| `/texts` | List editable message templates |
| `/edittext KEY` | Edit one message; then send replacement text |
| `/previewtext KEY` | Preview a message template |
| `/resettext KEY` | Restore default text |
| `/buttons KEY` | Inspect a template's buttons |
| `/addbutton KEY | LABEL | URL` | Add a URL button |
| `/editbutton KEY | INDEX | LABEL | URL` | Edit a button (1-based) |
| `/delbutton KEY | INDEX` | Remove a button (1-based) |

## Custom formatting

`(B)...(/B)`, `(I)...(/I)`, `(U)...(/U)`, `(S)...(/S)`, `(CODE)...(/CODE)`, `(PRE)...(/PRE)`, `(Q)...(/Q)`, `(SPOILER)...(/SPOILER)` and `(LINK url="https://example.com")...(/LINK)`. Text outside code/pre is converted to the configured Unicode small-caps style. URLs, IDs and code snippets should remain literal.

## Important storage limitation

The prototype copies stored channel messages directly using the clone bot's Telegram API identity. That bot must be able to access the official storage channel. The fully automatic token-only central relay is **not implemented in this foundation ZIP** and remains a production integration gate. Do not claim cloning is fully operational until the central storage access/relay test is complete.

## Not yet implemented

Premium billing/expiry workflows, full multi-channel FSub UI, 24-hour verification shortener, direct HTTP streaming server, collection creation/import dashboard, bulk regeneration policies, complete scheduled broadcasts, storage orphan scanner, and production-grade central relay. Tables and interfaces are present where relevant; these items need subsequent implementation and integration tests.

## License integration note

Before upstream code is copied into the private master repository, retain the source notices and comply with each upstream project's actual LICENSE file. Review GPL/Apache obligations separately. This scaffold does not copy third-party source files wholesale.
