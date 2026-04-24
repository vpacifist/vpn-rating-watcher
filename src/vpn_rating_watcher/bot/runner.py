from __future__ import annotations

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.bot.service import (
    ALLOWED_UPDATE_INTERVAL_HOURS,
    TelegramBotService,
    cleanup_temporary_chart_file,
    format_update_interval_label,
    parse_update_interval_hours,
)
from vpn_rating_watcher.charts.service import (
    CHART_MODE_MEDIAN_3D,
    CHART_THEME_DARK,
    CHART_THEME_LIGHT,
)


def _command_entries(*, web_app_url: str | None) -> list[tuple[str, str]]:
    web_description = "Open interactive chart page" if web_app_url else "Not configured"
    return [
        ("start", "Show bot intro and command list"),
        ("help", "Show full command list"),
        ("today", "Send today's chart or latest available"),
        ("chart", "Send latest chart"),
        ("chart_median", "Send latest chart (median 3d)"),
        ("theme_dark", "Use dark PNG theme in this chat"),
        ("theme_light", "Use light PNG theme in this chat"),
        ("last", "Show latest snapshot summary"),
        ("updates", "Choose how often update digests arrive"),
        ("set_updates", "Set digest interval, e.g. /set_updates 4h"),
        ("subscribe_here", "Subscribe current chat to daily chart"),
        ("unsubscribe_here", "Unsubscribe this chat from daily chart"),
        ("status", "Show current chat subscription status"),
        ("web", web_description),
    ]


def _commands_text(*, web_app_url: str | None) -> str:
    command_lines = "\n".join(
        f"/{name} - {description}"
        for name, description in _command_entries(web_app_url=web_app_url)
    )
    return "Available commands:\n" + command_lines


def _telegram_menu_commands(*, web_app_url: str | None) -> list[BotCommand]:
    return [
        BotCommand(command=name, description=description)
        for name, description in _command_entries(web_app_url=web_app_url)
    ]


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


def _updates_markup() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for interval_hours in ALLOWED_UPDATE_INTERVAL_HOURS:
        current_row.append(
            InlineKeyboardButton(
                text=format_update_interval_label(interval_hours),
                callback_data=f"updates:{interval_hours}",
            )
        )
        if len(current_row) == 4:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _updates_text(*, current_interval_hours: int) -> str:
    return (
        "Частота уведомлений.\n"
        f"Сейчас: каждые {format_update_interval_label(current_interval_hours)}.\n"
        "1ч = как сейчас, 2+ч = накопительный обзор изменений за окно.\n"
        "Пустые окна бот пропускает."
    )


def _resolve_telegram_chart_theme(*, chat_type: str) -> str:
    if chat_type in {"group", "supergroup", "channel"}:
        return CHART_THEME_DARK
    return CHART_THEME_DARK


def build_router(service: TelegramBotService, *, web_app_url: str | None = None) -> Router:
    local_router = Router(name="vpn-rating-watcher-commands")
    normalized_web_app_url = _normalize_web_app_url(web_app_url)
    web_markup = _web_link_markup(normalized_web_app_url)

    async def _remember_chat(message: Message) -> None:
        should_be_active = message.chat.type == "private"
        service.upsert_chat(
            chat_id=str(message.chat.id),
            chat_type=message.chat.type,
            title=_chat_title(message),
            is_active=should_be_active,
        )

    def _effective_chart_theme(message: Message) -> str:
        chat_theme = service.get_chat_theme(chat_id=str(message.chat.id))
        return chat_theme or _resolve_telegram_chart_theme(chat_type=message.chat.type)

    async def _send_permission_error(message: Message) -> None:
        await message.answer(
            "Не удалось отправить сообщение в этот чат. "
            "Проверьте, что боту разрешено писать сообщения и отключен режим только для админов."
        )

    @local_router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        await _remember_chat(message)
        await message.answer(
            "VPN Availability Watcher bot.\n" + _commands_text(web_app_url=normalized_web_app_url),
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
        chart, error = service.load_today_or_latest_chart(theme=_effective_chart_theme(message))
        if error:
            await message.answer(error)
            return
        assert chart is not None
        try:
            caption = (
                f"График доступности: {chart.chart_date.isoformat() if chart.chart_date else 'unknown'}"
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
        chart, error = service.load_latest_chart(theme=_effective_chart_theme(message))
        if error:
            await message.answer(error)
            return
        assert chart is not None
        try:
            chart_date_label = chart.chart_date.isoformat() if chart.chart_date else "unknown"
            caption = f"Последний график доступности ({chart_date_label})"
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
        chart, error = service.load_latest_chart(
            mode=CHART_MODE_MEDIAN_3D,
            theme=_effective_chart_theme(message),
        )
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

    @local_router.message(Command("updates"))
    async def updates_handler(message: Message) -> None:
        await _remember_chat(message)
        settings = service.get_chat_notification_settings(chat_id=str(message.chat.id))
        await message.answer(
            _updates_text(current_interval_hours=settings.update_interval_hours),
            reply_markup=_updates_markup(),
        )

    @local_router.message(Command("set_updates"))
    async def set_updates_handler(message: Message, command: CommandObject) -> None:
        await _remember_chat(message)
        try:
            interval_hours = parse_update_interval_hours(command.args)
        except ValueError as exc:
            await message.answer(str(exc))
            return

        updated_interval = service.set_chat_update_interval(
            chat_id=str(message.chat.id),
            chat_type=message.chat.type,
            title=_chat_title(message),
            update_interval_hours=interval_hours,
        )
        await message.answer(
            "Частота обновлений сохранена: "
            f"каждые {format_update_interval_label(updated_interval)}.\n"
            "Пустые окна бот пропускает."
        )

    @local_router.callback_query(F.data.startswith("updates:"))
    async def updates_callback_handler(callback: CallbackQuery) -> None:
        if callback.message is None or callback.data is None:
            await callback.answer()
            return

        try:
            interval_hours = parse_update_interval_hours(callback.data.split(":", 1)[1])
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return

        updated_interval = service.set_chat_update_interval(
            chat_id=str(callback.message.chat.id),
            chat_type=callback.message.chat.type,
            title=callback.message.chat.title,
            update_interval_hours=interval_hours,
        )
        await callback.message.edit_text(
            _updates_text(current_interval_hours=updated_interval),
            reply_markup=_updates_markup(),
        )
        await callback.answer(
            f"Обновления: каждые {format_update_interval_label(updated_interval)}."
        )

    @local_router.message(Command("theme_dark"))
    async def theme_dark_handler(message: Message) -> None:
        service.set_chat_theme(
            chat_id=str(message.chat.id),
            chat_type=message.chat.type,
            title=_chat_title(message),
            chart_theme=CHART_THEME_DARK,
        )
        await message.answer("PNG theme for this chat: dark.")

    @local_router.message(Command("theme_light"))
    async def theme_light_handler(message: Message) -> None:
        service.set_chat_theme(
            chat_id=str(message.chat.id),
            chat_type=message.chat.type,
            title=_chat_title(message),
            chart_theme=CHART_THEME_LIGHT,
        )
        await message.answer("PNG theme for this chat: light.")

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

    @local_router.message(Command("subscribe_here"))
    async def subscribe_here_handler(message: Message) -> None:
        try:
            service.set_chat_subscription(
                chat_id=str(message.chat.id),
                chat_type=message.chat.type,
                title=_chat_title(message),
                is_active=True,
            )
            await message.answer("✅ Этот чат подписан на daily chart.")
        except (TelegramForbiddenError, TelegramBadRequest):
            await _send_permission_error(message)

    @local_router.message(Command("unsubscribe_here"))
    async def unsubscribe_here_handler(message: Message) -> None:
        service.set_chat_subscription(
            chat_id=str(message.chat.id),
            chat_type=message.chat.type,
            title=_chat_title(message),
            is_active=False,
        )
        await message.answer("🛑 Этот чат отписан от daily chart.")

    @local_router.message(Command("status"))
    async def status_handler(message: Message) -> None:
        await _remember_chat(message)
        await message.answer(service.get_chat_status_text(chat_id=str(message.chat.id)))

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
    await bot.set_my_commands(_telegram_menu_commands(web_app_url=web_app_url))
    await dp.start_polling(bot)
