from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.bot.service import (
    _resolve_chart_path,
    cleanup_temporary_chart_file,
    get_latest_chart_for_date,
    upsert_telegram_chat,
)
from vpn_rating_watcher.db.models import TelegramChat


@dataclass(slots=True)
class DailyPostingResult:
    status: str
    message: str
    chart_date: date | None
    posted_count: int
    skipped_count: int
    active_chat_count: int


def parse_default_chat_ids(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []

    ids: list[str] = []
    for part in raw_value.split(","):
        chat_id = part.strip()
        if chat_id:
            ids.append(chat_id)

    return ids


def ensure_default_chats(session: Session, chat_ids: list[str]) -> int:
    initialized = 0
    for chat_id in chat_ids:
        existing = session.execute(
            select(TelegramChat).where(TelegramChat.chat_id == chat_id)
        ).scalar_one_or_none()
        if existing is None:
            initialized += 1
        upsert_telegram_chat(
            session=session,
            chat_id=chat_id,
            chat_type=None,
            title=None,
        )
    return initialized


def _active_chats_query() -> Select[tuple[TelegramChat]]:
    return (
        select(TelegramChat)
        .where(TelegramChat.is_active.is_(True))
        .order_by(TelegramChat.id.asc())
    )


async def _send_chart(*, token: str, chat_id: str, chart_path: Path, caption: str) -> None:
    bot = Bot(token=token)
    try:
        await bot.send_photo(
            chat_id=chat_id,
            photo=FSInputFile(chart_path),
            caption=caption,
        )
    finally:
        await bot.session.close()


def run_daily_posting_job(
    *,
    session_factory: sessionmaker[Session],
    token: str,
    default_chat_ids_raw: str | None,
    today: date | None = None,
    send_chart_func: Callable[..., Awaitable[None]] | None = None,
) -> DailyPostingResult:
    resolved_today = today or datetime.now(tz=timezone.utc).date()
    sender = send_chart_func or _send_chart

    with session_factory() as session:
        default_chat_ids = parse_default_chat_ids(default_chat_ids_raw)
        ensure_default_chats(session=session, chat_ids=default_chat_ids)

        chart = get_latest_chart_for_date(session=session, chart_date=resolved_today)
        if chart is None:
            active_chat_count = len(session.execute(_active_chats_query()).scalars().all())
            return DailyPostingResult(
                status="no_chart",
                message=f"No chart found for {resolved_today.isoformat()}; nothing posted.",
                chart_date=None,
                posted_count=0,
                skipped_count=0,
                active_chat_count=active_chat_count,
            )

        original_chart_path = chart.file_path
        chart_path, error = _resolve_chart_path(session=session, chart=chart)
        if error:
            active_chat_count = len(session.execute(_active_chats_query()).scalars().all())
            return DailyPostingResult(
                status="no_chart",
                message=error,
                chart_date=chart.chart_date,
                posted_count=0,
                skipped_count=0,
                active_chat_count=active_chat_count,
            )
        assert chart_path is not None
        chart.file_path = chart_path
        chart.is_temporary = chart_path != original_chart_path

        active_chats = session.execute(_active_chats_query()).scalars().all()
        chart_date_label = (
            chart.chart_date.isoformat() if chart.chart_date else resolved_today.isoformat()
        )
        caption = f"Daily chart: {chart_date_label}"

        posted_count = 0
        skipped_count = 0
        try:
            for chat in active_chats:
                if chat.last_posted_date is not None and chat.last_posted_date >= resolved_today:
                    skipped_count += 1
                    continue

                asyncio.run(
                    sender(
                        token=token,
                        chat_id=chat.chat_id,
                        chart_path=chart_path,
                        caption=caption,
                    )
                )
                chat.last_posted_date = resolved_today
                session.commit()
                posted_count += 1
        finally:
            cleanup_temporary_chart_file(chart)

        return DailyPostingResult(
            status="ok",
            message="Daily posting finished.",
            chart_date=chart.chart_date,
            posted_count=posted_count,
            skipped_count=skipped_count,
            active_chat_count=len(active_chats),
        )
