from file_sharing_bot.main import main
from file_sharing_bot.handlers.files import (
    upload, finish, newcollection, collectionpolicy, linkscollection, recover, bulkmaxfiles,
)
from file_sharing_bot.backup import add_backup_handlers
from file_sharing_bot.broadcast import add_broadcast_handlers
from file_sharing_bot.branding_config import IMAGE_URL


def test_runtime_imports_and_branding():
    assert callable(main)
    assert all(callable(fn) for fn in (
        upload, finish, newcollection, collectionpolicy, linkscollection, recover, bulkmaxfiles,
    ))
    assert callable(add_backup_handlers) and callable(add_broadcast_handlers)
    assert IMAGE_URL == "https://i.ibb.co/PGpMYwYY/Gemini-Generated-Image-a7tjlia7tjlia7tj.png"
