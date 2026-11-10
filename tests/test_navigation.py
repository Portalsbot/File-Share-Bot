from file_sharing_bot.settings import _navigation_keyboard

def test_start_navigation_has_about_help_and_optional_channel():
    markup = _navigation_keyboard({"channel_url": "https://t.me/example"}, "start")
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert any(button.callback_data == "nav:about" for button in buttons)
    assert any(button.callback_data == "nav:help" for button in buttons)
    assert any(button.url == "https://t.me/example" for button in buttons)
    assert not any(button.callback_data == "nav:start" for button in buttons)

def test_about_and_help_navigation_have_back_button():
    for page in ("about", "help"):
        markup = _navigation_keyboard({"channel_url": "https://t.me/example"}, page)
        buttons = [button for row in markup.inline_keyboard for button in row]
        assert any(button.callback_data == "nav:start" for button in buttons)
        assert any(button.callback_data == "nav:about" for button in buttons)
        assert any(button.callback_data == "nav:help" for button in buttons)
