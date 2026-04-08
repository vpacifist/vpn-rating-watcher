from vpn_rating_watcher.bot.runner import _commands_text, _normalize_web_app_url, _web_link_markup


def test_normalize_web_app_url_returns_none_for_blank_values() -> None:
    assert _normalize_web_app_url(None) is None
    assert _normalize_web_app_url("   ") is None


def test_normalize_web_app_url_strips_spaces() -> None:
    assert _normalize_web_app_url(" https://example.com/chart ") == "https://example.com/chart"


def test_commands_text_mentions_web_when_configured() -> None:
    text = _commands_text(web_app_url="https://example.com")
    assert "/web - Open interactive chart page" in text
    assert "/chart_median - Send latest chart (median 3d)" in text
    assert "/subscribe_here - Subscribe current chat to daily chart" in text
    assert "/status - Show current chat subscription status" in text


def test_commands_text_mentions_missing_web_when_not_configured() -> None:
    text = _commands_text(web_app_url=None)
    assert "/web - Not configured" in text


def test_web_link_markup_is_missing_without_url() -> None:
    assert _web_link_markup(None) is None


def test_web_link_markup_contains_button_url() -> None:
    markup = _web_link_markup("https://example.com")
    assert markup is not None
    assert markup.inline_keyboard[0][0].url == "https://example.com"
