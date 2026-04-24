from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.bot.service import (
    TelegramBotService,
    parse_update_interval_hours,
)
from vpn_rating_watcher.db.base import Base


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_private_chat_uses_hourly_updates_by_default() -> None:
    session_factory = _session_factory()
    service = TelegramBotService(session_factory=session_factory)

    service.upsert_chat(
        chat_id="12345",
        chat_type="private",
        title=None,
        is_active=True,
    )

    settings = service.get_chat_notification_settings(chat_id="12345")

    assert settings.is_active is True
    assert settings.update_interval_hours == 1


def test_set_chat_update_interval_persists_value() -> None:
    session_factory = _session_factory()
    service = TelegramBotService(session_factory=session_factory)

    updated_interval = service.set_chat_update_interval(
        chat_id="12345",
        chat_type="private",
        title=None,
        update_interval_hours=4,
    )

    settings = service.get_chat_notification_settings(chat_id="12345")

    assert updated_interval == 4
    assert settings.update_interval_hours == 4
    assert "каждые 4ч" in service.get_chat_status_text(chat_id="12345")


def test_parse_update_interval_hours_accepts_supported_values() -> None:
    assert parse_update_interval_hours("1h") == 1
    assert parse_update_interval_hours("4") == 4


def test_parse_update_interval_hours_rejects_unsupported_values() -> None:
    try:
        parse_update_interval_hours("5h")
    except ValueError as exc:
        assert "Unsupported update interval" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected ValueError for unsupported interval")
