from __future__ import annotations

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.bot.service import TelegramBotService, cleanup_temporary_chart_file
from vpn_rating_watcher.charts.service import CHART_MODE_MEDIAN_3D


def _commands_text(*, web_app_url: str | None) -> str:
    web_command = "/web - Open interactive chart page" if web_app_url else "/web - Not configured"
    return (
        "Available commands:\n"
        "/today - Send today's chart, or latest if today's is missing\n"
        "/chart - Send latest chart\n"
        "/chart_median - Send latest chart (median 3d)\n"
        "/last - Show latest snapshot summary\n"
        f"{web_command}\n"
        "/help - Show this help"
    )


def _chat_title(message: Message) -> str | None:
    chat = message.chat
    return chat.title if chat.title else None


def _normalize_web_app_url(web_app_url: str | None) -> str | None:
    if web_app_url is None:
        return None
    normalized = web_app_url.strip()
    if not normalized:
        return None
    return normalized


def _web_link_markup(web_app_url: str | None) -> InlineKeyboardMarkup | None:
    if not web_app_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть веб-график",
                    url=web_app_url,
                )
            ]
        ]
    )


def build_router(service: TelegramBotService, *, web_app_url: str | None = None) -> Router:
    local_router = Router(name="vpn-rating-watcher-commands")
    normalized_web_app_url = _normalize_web_app_url(web_app_url)
    web_markup = _web_link_markup(normalized_web_app_url)

    async def _remember_chat(message: Message) -> None:
        service.upsert_chat(
            chat_id=str(message.chat.id),
            chat_type=message.chat.type,
            title=_chat_title(message),
        )

    @local_router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        await _remember_chat(message)
        await message.answer(
            "VPN Rating Watcher bot.\n" + _commands_text(web_app_url=normalized_web_app_url),
            reply_markup=web_markup,
        )

    @local_router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await _remember_chat(message)
        await message.answer(
            _commands_text(web_app_url=normalized_web_app_url),
            reply_markup=web_markup,
        )

    @local_router.message(Command("today"))
    async def today_handler(message: Message) -> None:
        await _remember_chat(message)
        chart, error = service.load_today_or_latest_chart()
        if error:
            await message.answer(error)
            return
        assert chart is not None
        try:
            caption = (
                f"Chart date: {chart.chart_date.isoformat() if chart.chart_date else 'unknown'}"
            )
            await message.answer_photo(
                photo=FSInputFile(chart.file_path),
                caption=caption,
                reply_markup=web_markup,
            )
        finally:
            cleanup_temporary_chart_file(chart)

    @local_router.message(Command("chart"))
    async def chart_handler(message: Message) -> None:
        await _remember_chat(message)
        chart, error = service.load_latest_chart()
        if error:
            await message.answer(error)
            return
        assert chart is not None
        try:
            chart_date_label = chart.chart_date.isoformat() if chart.chart_date else "unknown"
            caption = f"Latest chart ({chart_date_label})"
            await message.answer_photo(
                photo=FSInputFile(chart.file_path),
                caption=caption,
                reply_markup=web_markup,
            )
        finally:
            cleanup_temporary_chart_file(chart)

    @local_router.message(Command("chart_median"))
    async def chart_median_handler(message: Message) -> None:
        await _remember_chat(message)
        chart, error = service.load_latest_chart(mode=CHART_MODE_MEDIAN_3D)
        if error:
            await message.answer(error)
            return
        assert chart is not None
        try:
            chart_date_label = chart.chart_date.isoformat() if chart.chart_date else "unknown"
            caption = f"Latest chart median 3d ({chart_date_label})"
            await message.answer_photo(
                photo=FSInputFile(chart.file_path),
                caption=caption,
                reply_markup=web_markup,
            )
        finally:
            cleanup_temporary_chart_file(chart)

    @local_router.message(Command("last"))
    async def last_handler(message: Message) -> None:
        await _remember_chat(message)
        await message.answer(service.load_last_snapshot_text(), reply_markup=web_markup)

    @local_router.message(Command("web"))
    async def web_handler(message: Message) -> None:
        await _remember_chat(message)
        if not normalized_web_app_url:
            await message.answer(
                "WEB_APP_URL не настроен. Добавьте публичный URL web-сервиса в окружение."
            )
            return
        await message.answer(
            f"Интерактивный график: {normalized_web_app_url}",
            reply_markup=web_markup,
        )

    return local_router


async def run_polling(
    *,
    token: str,
    session_factory: sessionmaker[Session],
    web_app_url: str | None = None,
) -> None:
    service = TelegramBotService(session_factory=session_factory)

    dp = Dispatcher()
    dp.include_router(build_router(service, web_app_url=web_app_url))

    bot = Bot(token=token)
    await dp.start_polling(bot)
