from __future__ import annotations

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.bot.service import TelegramBotService

def _commands_text() -> str:
    return (
        "Available commands:\n"
        "/today - Send today's chart, or latest if today's is missing\n"
        "/chart - Send latest chart\n"
        "/last - Show latest snapshot summary\n"
        "/help - Show this help"
    )


def _chat_title(message: Message) -> str | None:
    chat = message.chat
    return chat.title if chat.title else None


def build_router(service: TelegramBotService) -> Router:
    local_router = Router(name="vpn-rating-watcher-commands")

    async def _remember_chat(message: Message) -> None:
        service.upsert_chat(
            chat_id=str(message.chat.id),
            chat_type=message.chat.type,
            title=_chat_title(message),
        )

    @local_router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        await _remember_chat(message)
        await message.answer("VPN Rating Watcher bot.\n" + _commands_text())

    @local_router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await _remember_chat(message)
        await message.answer(_commands_text())

    @local_router.message(Command("today"))
    async def today_handler(message: Message) -> None:
        await _remember_chat(message)
        chart, error = service.load_today_or_latest_chart()
        if error:
            await message.answer(error)
            return
        assert chart is not None
        await message.answer_photo(
            photo=FSInputFile(chart.file_path),
            caption=f"Chart date: {chart.chart_date.isoformat() if chart.chart_date else 'unknown'}",
        )

    @local_router.message(Command("chart"))
    async def chart_handler(message: Message) -> None:
        await _remember_chat(message)
        chart, error = service.load_latest_chart()
        if error:
            await message.answer(error)
            return
        assert chart is not None
        await message.answer_photo(
            photo=FSInputFile(chart.file_path),
            caption=f"Latest chart ({chart.chart_date.isoformat() if chart.chart_date else 'unknown'})",
        )

    @local_router.message(Command("last"))
    async def last_handler(message: Message) -> None:
        await _remember_chat(message)
        await message.answer(service.load_last_snapshot_text())

    return local_router


async def run_polling(*, token: str, session_factory: sessionmaker[Session]) -> None:
    service = TelegramBotService(session_factory=session_factory)

    dp = Dispatcher()
    dp.include_router(build_router(service))

    bot = Bot(token=token)
    await dp.start_polling(bot)
