from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.bot.service import TelegramBotService
from vpn_rating_watcher.db.base import Base


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_group_upsert_preserves_existing_subscription_state() -> None:
    session_factory = _session_factory()
    service = TelegramBotService(session_factory=session_factory)

    service.set_chat_subscription(
        chat_id="-100123",
        chat_type="supergroup",
        title="team",
        is_active=True,
    )

    service.upsert_chat(
        chat_id="-100123",
        chat_type="supergroup",
        title="team renamed",
        is_active=False,
    )

    assert service.is_chat_subscribed(chat_id="-100123") is True


def test_private_upsert_still_reactivates_chat() -> None:
    session_factory = _session_factory()
    service = TelegramBotService(session_factory=session_factory)

    service.set_chat_subscription(
        chat_id="12345",
        chat_type="private",
        title=None,
        is_active=False,
    )

    service.upsert_chat(
        chat_id="12345",
        chat_type="private",
        title=None,
        is_active=True,
    )

    assert service.is_chat_subscribed(chat_id="12345") is True
