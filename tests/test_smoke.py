from file_sharing_bot.main import main
from file_sharing_bot.handlers.files import (
    upload, finish, newcollection, collectionpolicy, linkscollection, recover,
    bulkmaxfiles, setstoragechannel, bulkregenerate,
)
from file_sharing_bot.backup import add_backup_handlers
from file_sharing_bot.broadcast import add_broadcast_handlers
from file_sharing_bot.branding_config import IMAGE_URL

from file_sharing_bot.fsubs import add_fsubs_handlers

def test_runtime_imports_and_branding():
    assert callable(main)
    assert callable(add_fsubs_handlers)
    assert all(callable(fn) for fn in (
        upload, finish, newcollection, collectionpolicy, linkscollection,
        recover, bulkmaxfiles, setstoragechannel, bulkregenerate,
    ))
    assert callable(add_backup_handlers) and callable(add_broadcast_handlers)
    assert IMAGE_URL == "https://i.ibb.co/PGpMYwYY/Gemini-Generated-Image-a7tjlia7tjlia7tj.png"
