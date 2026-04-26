from __future__ import annotations

import asyncio
import html
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.bot.service import format_update_interval_label
from vpn_rating_watcher.charts.service import ChartGenerationResult, generate_historical_line_chart
from vpn_rating_watcher.db.models import Snapshot, TelegramChat, Vpn, VpnSnapshotResult
from vpn_rating_watcher.db.persistence import PersistSnapshotResult, persist_scrape_result
from vpn_rating_watcher.jobs.daily_telegram_post import ensure_default_chats, parse_default_chat_ids
from vpn_rating_watcher.scraper.models import ScrapeResult
from vpn_rating_watcher.scraper.service import scrape_once

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SnapshotChangeLine:
    kind: str
    vpn_name: str
    sort_rank: int
    old_rank: int | None
    new_rank: int | None
    old_score: int | None
    new_score: int | None


@dataclass(slots=True)
class SnapshotDiffSummary:
    changed_count: int
    new_count: int
    removed_count: int
    top_changes: list[str]
    changed_details: list[SnapshotChangeLine]
    new_details: list[SnapshotChangeLine]
    removed_details: list[SnapshotChangeLine]


@dataclass(slots=True)
class NotificationDigestSummary:
    changed_count: int
    new_count: int
    removed_count: int
    top_changes: list[str]
    total_change_count: int
    snapshot_count: int
    window_start: datetime
    window_end: datetime

    @property
    def has_changes(self) -> bool:
        return self.changed_count > 0 or self.new_count > 0 or self.removed_count > 0


@dataclass(slots=True)
class HourlySyncResult:
    status: str
    message: str
    source_name: str
    content_hash: str | None
    snapshot_id: int | None
    chart_id: int | None
    notified_count: int
    active_chat_count: int
    changed_count: int
    new_count: int
    removed_count: int


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _active_chats_query() -> Select[tuple[TelegramChat]]:
    return (
        select(TelegramChat)
        .where(TelegramChat.is_active.is_(True))
        .where(TelegramChat.chat_type == "private")
        .order_by(TelegramChat.id.asc())
    )


def _latest_snapshot_by_source(session: Session, source_name: str) -> Snapshot | None:
    return session.execute(
        select(Snapshot)
        .where(Snapshot.source_name == source_name)
        .order_by(desc(Snapshot.fetched_at), desc(Snapshot.id))
        .limit(1)
    ).scalar_one_or_none()


def _snapshot_before(
    session: Session,
    *,
    source_name: str,
    fetched_before: datetime,
) -> Snapshot | None:
    return session.execute(
        select(Snapshot)
        .where(Snapshot.source_name == source_name)
        .where(Snapshot.fetched_at < fetched_before)
        .order_by(desc(Snapshot.fetched_at), desc(Snapshot.id))
        .limit(1)
    ).scalar_one_or_none()


def _snapshots_in_window(
    session: Session,
    *,
    source_name: str,
    fetched_after: datetime | None,
    fetched_until: datetime,
) -> list[Snapshot]:
    stmt = (
        select(Snapshot)
        .where(Snapshot.source_name == source_name)
        .where(Snapshot.fetched_at <= fetched_until)
        .order_by(Snapshot.fetched_at.asc(), Snapshot.id.asc())
    )
    if fetched_after is not None:
        stmt = stmt.where(Snapshot.fetched_at > fetched_after)
    return session.execute(stmt).scalars().all()


def _snapshot_scores(session: Session, snapshot_id: int) -> dict[str, tuple[int, int]]:
    rows = session.execute(
        select(Vpn.name, VpnSnapshotResult.rank_position, VpnSnapshotResult.score)
        .join(Vpn, Vpn.id == VpnSnapshotResult.vpn_id)
        .where(VpnSnapshotResult.snapshot_id == snapshot_id)
    ).all()
    return {name: (rank, score) for name, rank, score in rows}


def _format_rank_change(old_rank: int | None, new_rank: int | None) -> str:
    if old_rank == new_rank:
        return f"#{new_rank}"
    if old_rank is not None and new_rank is not None:
        direction = "⬆️" if new_rank < old_rank else "🔻"
        return f"#{old_rank}{direction}#{new_rank}"
    return f"#{new_rank}"


def _format_change_line(change: SnapshotChangeLine) -> str:
    if change.kind == "changed":
        rank_part = _format_rank_change(change.old_rank, change.new_rank)
        return f"{rank_part} {change.vpn_name} ({change.old_score}→{change.new_score})"
    if change.kind == "new":
        return f"Новый: #{change.new_rank} {change.vpn_name}, score {change.new_score}"
    return f"Удалён: {change.vpn_name}, было #{change.old_rank}, score {change.old_score}"


def _plural_ru(value: int, one: str, few: str, many: str) -> str:
    last_two_digits = value % 100
    if 11 <= last_two_digits <= 14:
        return many
    last_digit = value % 10
    if last_digit == 1:
        return one
    if 2 <= last_digit <= 4:
        return few
    return many


def _format_snapshot_count(value: int) -> str:
    return f"{value} {_plural_ru(value, 'снимок', 'снимка', 'снимков')}"


def _format_change_count(value: int) -> str:
    return f"{value} {_plural_ru(value, 'изменение', 'изменения', 'изменений')}"


def _format_digest_window(start: datetime, end: datetime) -> str:
    if start.date() == end.date():
        return f"{start.strftime('%d.%m %H:%M')}–{end.strftime('%H:%M UTC')}"
    return f"{start.strftime('%d.%m %H:%M')}–{end.strftime('%d.%m %H:%M UTC')}"


def _format_total_line(digest: NotificationDigestSummary) -> str:
    details: list[str] = []
    if digest.new_count:
        details.append(f"{digest.new_count} {_plural_ru(digest.new_count, 'новый', 'новых', 'новых')}")
    if digest.removed_count:
        details.append(
            f"{digest.removed_count} {_plural_ru(digest.removed_count, 'удалённый', 'удалённых', 'удалённых')}"
        )

    total_line = f"Итого: {_format_change_count(digest.total_change_count)}"
    if details:
        total_line = f"{total_line} ({', '.join(details)})"
    return total_line


def _diff_snapshots(
    session: Session,
    *,
    old_snapshot_id: int | None,
    new_snapshot_id: int,
) -> SnapshotDiffSummary:
    new_scores = _snapshot_scores(session=session, snapshot_id=new_snapshot_id)
    if old_snapshot_id is None:
        new_details = [
            SnapshotChangeLine(
                kind="new",
                vpn_name=vpn_name,
                sort_rank=rank,
                old_rank=None,
                new_rank=rank,
                old_score=None,
                new_score=score,
            )
            for vpn_name, (rank, score) in sorted(new_scores.items(), key=lambda item: item[1][0])
        ]
        return SnapshotDiffSummary(
            changed_count=0,
            new_count=len(new_details),
            removed_count=0,
            top_changes=[_format_change_line(change) for change in new_details],
            changed_details=[],
            new_details=new_details,
            removed_details=[],
        )

    old_scores = _snapshot_scores(session=session, snapshot_id=old_snapshot_id)

    changed_names = sorted(
        (
            name
            for name in (old_scores.keys() & new_scores.keys())
            if old_scores[name] != new_scores[name]
        ),
        key=lambda vpn_name: new_scores[vpn_name][0],
    )
    new_names = sorted(
        new_scores.keys() - old_scores.keys(),
        key=lambda vpn_name: new_scores[vpn_name][0],
    )
    removed_names = sorted(old_scores.keys() - new_scores.keys())

    changed_details = [
        SnapshotChangeLine(
            kind="changed",
            vpn_name=name,
            sort_rank=new_scores[name][0],
            old_rank=old_scores[name][0],
            new_rank=new_scores[name][0],
            old_score=old_scores[name][1],
            new_score=new_scores[name][1],
        )
        for name in changed_names
    ]
    new_details = [
        SnapshotChangeLine(
            kind="new",
            vpn_name=name,
            sort_rank=new_scores[name][0],
            old_rank=None,
            new_rank=new_scores[name][0],
            old_score=None,
            new_score=new_scores[name][1],
        )
        for name in new_names
    ]
    removed_details = [
        SnapshotChangeLine(
            kind="removed",
            vpn_name=name,
            sort_rank=old_scores[name][0],
            old_rank=old_scores[name][0],
            new_rank=None,
            old_score=old_scores[name][1],
            new_score=None,
        )
        for name in removed_names
    ]

    top_changes = [
        _format_change_line(change)
        for change in (changed_details + new_details + removed_details)
    ]

    return SnapshotDiffSummary(
        changed_count=len(changed_details),
        new_count=len(new_details),
        removed_count=len(removed_details),
        top_changes=top_changes,
        changed_details=changed_details,
        new_details=new_details,
        removed_details=removed_details,
    )


def _is_due_for_notification(
    *,
    chat: TelegramChat,
    current_snapshot: Snapshot,
    pending_snapshots: list[Snapshot],
) -> bool:
    if chat.update_interval_hours <= 1:
        return True
    if not pending_snapshots:
        return False

    current_fetched_at = _ensure_utc(current_snapshot.fetched_at)
    interval = timedelta(hours=chat.update_interval_hours)

    if chat.last_notified_at is not None:
        return current_fetched_at >= _ensure_utc(chat.last_notified_at) + interval

    oldest_pending = _ensure_utc(pending_snapshots[0].fetched_at)
    return current_fetched_at - oldest_pending >= interval


def _aggregate_notification_summary(
    session: Session,
    *,
    source_name: str,
    chat: TelegramChat,
    current_snapshot: Snapshot,
) -> NotificationDigestSummary | None:
    current_fetched_at = _ensure_utc(current_snapshot.fetched_at)
    if chat.update_interval_hours <= 1:
        baseline = _snapshot_before(
            session,
            source_name=source_name,
            fetched_before=current_fetched_at,
        )
        diff = _diff_snapshots(
            session=session,
            old_snapshot_id=baseline.id if baseline is not None else None,
            new_snapshot_id=current_snapshot.id,
        )
        return NotificationDigestSummary(
            changed_count=diff.changed_count,
            new_count=diff.new_count,
            removed_count=diff.removed_count,
            top_changes=diff.top_changes,
            total_change_count=diff.changed_count + diff.new_count + diff.removed_count,
            snapshot_count=1,
            window_start=current_fetched_at,
            window_end=current_fetched_at,
        )

    fetched_after = _ensure_utc(chat.last_notified_at) if chat.last_notified_at else None
    pending_snapshots = _snapshots_in_window(
        session,
        source_name=source_name,
        fetched_after=fetched_after,
        fetched_until=current_fetched_at,
    )
    if not _is_due_for_notification(
        chat=chat,
        current_snapshot=current_snapshot,
        pending_snapshots=pending_snapshots,
    ):
        return None

    latest_change_by_name: dict[str, SnapshotChangeLine] = {}
    changed_names: set[str] = set()
    new_names: set[str] = set()
    removed_names: set[str] = set()

    previous_snapshot = (
        _snapshot_before(session, source_name=source_name, fetched_before=_ensure_utc(pending_snapshots[0].fetched_at))
        if pending_snapshots
        else None
    )

    for snapshot in pending_snapshots:
        diff = _diff_snapshots(
            session=session,
            old_snapshot_id=previous_snapshot.id if previous_snapshot is not None else None,
            new_snapshot_id=snapshot.id,
        )
        for change in diff.changed_details:
            changed_names.add(change.vpn_name)
            latest_change_by_name[change.vpn_name] = change
        for change in diff.new_details:
            new_names.add(change.vpn_name)
            latest_change_by_name[change.vpn_name] = change
        for change in diff.removed_details:
            removed_names.add(change.vpn_name)
            latest_change_by_name[change.vpn_name] = change
        previous_snapshot = snapshot

    if not latest_change_by_name:
        return NotificationDigestSummary(
            changed_count=0,
            new_count=0,
            removed_count=0,
            top_changes=[],
            total_change_count=0,
            snapshot_count=len(pending_snapshots),
            window_start=_ensure_utc(pending_snapshots[0].fetched_at),
            window_end=current_fetched_at,
        )

    ordered_changes = sorted(
        latest_change_by_name.values(),
        key=lambda change: (
            {"changed": 0, "new": 1, "removed": 2}[change.kind],
            change.sort_rank,
            change.vpn_name.casefold(),
        ),
    )

    return NotificationDigestSummary(
        changed_count=len(changed_names),
        new_count=len(new_names),
        removed_count=len(removed_names),
        top_changes=[_format_change_line(change) for change in ordered_changes],
        total_change_count=len(ordered_changes),
        snapshot_count=len(pending_snapshots),
        window_start=_ensure_utc(pending_snapshots[0].fetched_at),
        window_end=current_fetched_at,
    )


async def _send_text(*, token: str, chat_id: str, text: str) -> None:
    bot = Bot(token=token)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    finally:
        await bot.session.close()


def _run_awaitable_sync(awaitable_factory: Callable[[], Awaitable[None]]) -> None:
    runner_error: BaseException | None = None

    def _runner() -> None:
        nonlocal runner_error
        try:
            asyncio.run(awaitable_factory())
        except BaseException as exc:  # pragma: no cover
            runner_error = exc

    thread = threading.Thread(target=_runner)
    thread.start()
    thread.join()
    if runner_error is not None:
        raise runner_error


def _build_update_message(
    *,
    saved: PersistSnapshotResult,
    chart: ChartGenerationResult,
    digest: NotificationDigestSummary,
    interval_hours: int,
) -> str:
    title_kind = "обновление" if interval_hours == 1 else "обзор"
    interval_label = format_update_interval_label(interval_hours)
    lines = [
        f"✅ VPN Rating Watcher · {title_kind} за {interval_label}",
        f"{_format_digest_window(digest.window_start, digest.window_end)} · {_format_snapshot_count(digest.snapshot_count)}",
        "",
        _format_total_line(digest),
    ]

    if digest.top_changes:
        lines.extend(f"• {html.escape(line)}" for line in digest.top_changes)

    lines.extend(["", f"<i>snapshot {saved.snapshot_id} · chart {chart.chart_id}</i>"])
    return "\n".join(lines)


def run_hourly_sync_job(
    *,
    session_factory: sessionmaker[Session],
    source_name: str,
    source_url: str,
    artifacts_dir: str,
    headless: bool,
    token: str | None,
    default_chat_ids_raw: str | None,
    scrape_func: Callable[..., ScrapeResult] = scrape_once,
    chart_func: Callable[..., ChartGenerationResult] = generate_historical_line_chart,
    send_message_func: Callable[..., Awaitable[None]] | None = None,
) -> HourlySyncResult:
    logger.info("hourly_sync.started", extra={"source_name": source_name, "source_url": source_url})

    scrape_result = scrape_func(
        source_url=source_url,
        artifacts_dir=artifacts_dir,
        headless=headless,
    )

    sender = send_message_func or _send_text
    notified_count = 0

    with session_factory() as session:
        previous = _latest_snapshot_by_source(session=session, source_name=source_name)
        previous_id = previous.id if previous else None

    with session_factory() as session:
        saved = persist_scrape_result(
            session=session,
            scrape_result=scrape_result,
            source_name=source_name,
        )

        default_chat_ids = parse_default_chat_ids(default_chat_ids_raw)
        ensure_default_chats(session=session, chat_ids=default_chat_ids)
        active_chats = session.execute(_active_chats_query()).scalars().all()
        active_chat_count = len(active_chats)

        if saved.status != "created":
            logger.info(
                "hourly_sync.no_change",
                extra={"source_name": source_name, "content_hash": saved.content_hash},
            )
            return HourlySyncResult(
                status="no_change",
                message="No source changes detected; chart was not regenerated.",
                source_name=source_name,
                content_hash=saved.content_hash,
                snapshot_id=saved.snapshot_id,
                chart_id=None,
                notified_count=0,
                active_chat_count=active_chat_count,
                changed_count=0,
                new_count=0,
                removed_count=0,
            )

        assert saved.snapshot_id is not None
        current_snapshot = session.get(Snapshot, saved.snapshot_id)
        assert current_snapshot is not None

        diff = _diff_snapshots(
            session=session,
            old_snapshot_id=previous_id,
            new_snapshot_id=saved.snapshot_id,
        )
        chart = chart_func(session=session, source_name=source_name)

        if token:
            for chat in active_chats:
                digest = _aggregate_notification_summary(
                    session,
                    source_name=source_name,
                    chat=chat,
                    current_snapshot=current_snapshot,
                )
                if digest is None or not digest.has_changes:
                    continue

                message_text = _build_update_message(
                    saved=saved,
                    chart=chart,
                    digest=digest,
                    interval_hours=chat.update_interval_hours,
                )
                chat_id = chat.chat_id
                try:
                    _run_awaitable_sync(
                        lambda chat_id=chat_id, text=message_text: sender(
                            token=token,
                            chat_id=chat_id,
                            text=text,
                        )
                    )
                except TelegramForbiddenError:
                    chat.is_active = False
                    session.commit()
                    logger.warning(
                        "hourly_sync.chat_forbidden_marked_inactive",
                        extra={"chat_id": chat_id},
                    )
                else:
                    chat.last_notified_at = current_snapshot.fetched_at
                    session.commit()
                    notified_count += 1
        else:
            logger.warning("hourly_sync.token_missing_skip_notify")

    logger.info(
        "hourly_sync.updated",
        extra={
            "source_name": source_name,
            "snapshot_id": saved.snapshot_id,
            "chart_id": chart.chart_id,
            "changed_count": diff.changed_count,
            "new_count": diff.new_count,
            "removed_count": diff.removed_count,
            "notified_count": notified_count,
        },
    )

    return HourlySyncResult(
        status="updated",
        message="Source changed; snapshot saved, chart regenerated, notifications sent.",
        source_name=source_name,
        content_hash=saved.content_hash,
        snapshot_id=saved.snapshot_id,
        chart_id=chart.chart_id,
        notified_count=notified_count,
        active_chat_count=active_chat_count,
        changed_count=diff.changed_count,
        new_count=diff.new_count,
        removed_count=diff.removed_count,
    )
