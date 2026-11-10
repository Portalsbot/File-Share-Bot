import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from file_sharing_bot import branding

def test_branded_sender_adds_close_without_dummy_button(monkeypatch, tmp_path):
    photo = tmp_path / "branding.jpg"
    photo.write_bytes(b"fake-image")
    monkeypatch.setattr(branding, "IMAGE_PATH", photo)
    bot = SimpleNamespace(send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)))
    custom = InlineKeyboardMarkup([[InlineKeyboardButton("ABOUT", callback_data="nav:about")]])
    asyncio.run(branding.send_branded(
        bot, 123, "Hello", image_url="https://example.com/image.jpg",
        reply_markup=custom, small_caps=True,
    ))
    markup = bot.send_photo.await_args.kwargs["reply_markup"]
    buttons = [button for row in markup.inline_keyboard for button in row]
    close = [button for button in buttons if button.callback_data == branding.CLOSE_CALLBACK_DATA]
    assert len(close) == 1
    assert close[0].text == branding.CLOSE_BUTTON_TEXT
    assert any(button.callback_data == "nav:about" for button in buttons)
    assert not any(button.url == "https://t.me/" for button in buttons)

def test_every_caption_chunk_has_close(monkeypatch, tmp_path):
    photo = tmp_path / "branding.jpg"
    photo.write_bytes(b"fake-image")
    monkeypatch.setattr(branding, "IMAGE_PATH", photo)
    bot = SimpleNamespace(send_photo=AsyncMock(side_effect=[
        SimpleNamespace(message_id=1), SimpleNamespace(message_id=2)
    ]))
    asyncio.run(branding.send_branded(bot, 123, "x" * 900, image_url="https://example.com/image.jpg"))
    assert bot.send_photo.await_count == 2
    for call in bot.send_photo.await_args_list:
        buttons = [button for row in call.kwargs["reply_markup"].inline_keyboard for button in row]
        assert sum(button.callback_data == branding.CLOSE_CALLBACK_DATA for button in buttons) == 1
