from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.charts.service import ChartGenerationResult, generate_historical_line_chart
from vpn_rating_watcher.db.models import Snapshot, TelegramChat, Vpn, VpnSnapshotResult
from vpn_rating_watcher.db.persistence import PersistSnapshotResult, persist_scrape_result
from vpn_rating_watcher.jobs.daily_telegram_post import ensure_default_chats, parse_default_chat_ids
from vpn_rating_watcher.scraper.models import ScrapeResult
from vpn_rating_watcher.scraper.service import scrape_once

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SnapshotDiffSummary:
    changed_count: int
    new_count: int
    removed_count: int
    top_changes: list[str]


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


def _snapshot_scores(session: Session, snapshot_id: int) -> dict[str, tuple[int, int]]:
    rows = session.execute(
        select(Vpn.name, VpnSnapshotResult.rank_position, VpnSnapshotResult.score)
        .join(Vpn, Vpn.id == VpnSnapshotResult.vpn_id)
        .where(VpnSnapshotResult.snapshot_id == snapshot_id)
    ).all()
    return {name: (rank, score) for name, rank, score in rows}


def _diff_snapshots(
    session: Session,
    *,
    old_snapshot_id: int | None,
    new_snapshot_id: int,
) -> SnapshotDiffSummary:
    new_scores = _snapshot_scores(session=session, snapshot_id=new_snapshot_id)
    if old_snapshot_id is None:
        top_names = sorted(new_scores, key=lambda vpn_name: new_scores[vpn_name][0])[:5]
        return SnapshotDiffSummary(
            changed_count=0,
            new_count=len(new_scores),
            removed_count=0,
            top_changes=[
                f"new: #{new_scores[vpn_name][0]} {vpn_name} ({new_scores[vpn_name][1]})"
                for vpn_name in top_names
            ],
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

    top_changes: list[str] = []
    for name in changed_names[:5]:
        old_rank, old_score = old_scores[name]
        new_rank, new_score = new_scores[name]
        top_changes.append(
            f"chg: {name} #{old_rank}->{new_rank} score {old_score}->{new_score}"
        )

    for name in new_names[: max(0, 5 - len(top_changes))]:
        new_rank, new_score = new_scores[name]
        top_changes.append(f"new: #{new_rank} {name} ({new_score})")
    for name in removed_names[: max(0, 5 - len(top_changes))]:
        old_rank, old_score = old_scores[name]
        top_changes.append(f"removed: #{old_rank} {name} ({old_score})")

    return SnapshotDiffSummary(
        changed_count=len(changed_names),
        new_count=len(new_names),
        removed_count=len(removed_names),
        top_changes=top_changes,
    )


async def _send_text(*, token: str, chat_id: str, text: str) -> None:
    bot = Bot(token=token)
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    finally:
        await bot.session.close()


def _run_awaitable_sync(awaitable_factory: Callable[[], Awaitable[None]]) -> None:
    runner_error: BaseException | None = None

    def _runner() -> None:
        nonlocal runner_error
        try:
            asyncio.run(awaitable_factory())
        except BaseException as exc:  # pragma: no cover - re-raised in caller thread
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
    diff: SnapshotDiffSummary,
) -> str:
    total_changes = diff.changed_count + diff.new_count + diff.removed_count
    all_changes_fit_top = total_changes > 0 and len(diff.top_changes) == total_changes

    lines = [
        "✅ VPN Rating Watcher: база обновлена",
        f"Snapshot ID: {saved.snapshot_id}",
        f"Chart ID: {chart.chart_id} ({chart.end_date.isoformat()})",
    ]
    if not (all_changes_fit_top and diff.new_count == 0 and diff.removed_count == 0):
        if diff.new_count == 0 and diff.removed_count == 0:
            lines.append(f"Изменения: changed={diff.changed_count}")
        else:
            lines.append(
                "Изменения: "
                f"changed={diff.changed_count}, new={diff.new_count}, removed={diff.removed_count}"
            )

    if diff.top_changes:
        if not all_changes_fit_top:
            lines.append("Top changes:")
        lines.extend(f"- {line}" for line in diff.top_changes)
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
        diff = _diff_snapshots(
            session=session,
            old_snapshot_id=previous_id,
            new_snapshot_id=saved.snapshot_id,
        )
        chart = chart_func(session=session, source_name=source_name)

        message_text = _build_update_message(
            saved=saved,
            chart=chart,
            diff=diff,
        )

        if token:
            for chat in active_chats:
                chat_id = chat.chat_id
                try:
                    _run_awaitable_sync(
                        lambda chat_id=chat_id: sender(
                            token=token,
                            chat_id=chat_id,
                            text=message_text,
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
