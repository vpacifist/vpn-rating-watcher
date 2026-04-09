from vpn_rating_watcher.web.app import index


def test_index_html_prioritizes_system_theme_and_falls_back_to_dark() -> None:
    html = index()

    assert "const initialPreference = getInitialThemePreference(stored);" in html
    assert "return 'system';" in html
    assert "storedPreference === 'light' || storedPreference === 'dark'" in html
    assert "? storedPreference" in html
    assert ": 'dark'" in html
    assert "const normalizedPreference =" in html
    assert "preference === 'system' && !hasSystemThemePreference" in html
    assert "? 'dark'" in html
    assert ": preference;" in html


def test_index_html_disables_unavailable_system_theme_option() -> None:
    html = index()

    assert "systemButton.disabled = !hasSystemThemePreference;" in html
    assert "systemButton.classList.toggle('system-unavailable', !hasSystemThemePreference);" in html
    assert "system недоступен: браузер не сообщает тему устройства" in html
    assert "id='themeHint'" in html
