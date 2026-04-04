"""backfill generated_chart metadata and harden constraints

Revision ID: 20260404_0003
Revises: 20260404_0002
Create Date: 2026-04-04 00:30:00.000000

"""

from __future__ import annotations

import re
from datetime import date

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260404_0003"
down_revision = "20260404_0002"
branch_labels = None
depends_on = None

_TABLE_NAME = "generated_chart"
_FILENAME_RE = re.compile(
    r"linechart_(?P<source>.+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.png$"
)
_TARGET_COLUMNS = ("source_name", "range_start_date", "range_end_date", "range_days")


def _maybe_parse_from_file_path(
    file_path: str | None,
) -> tuple[str | None, date | None, date | None]:
    if not file_path:
        return None, None, None
    filename = file_path.rsplit("/", maxsplit=1)[-1]
    match = _FILENAME_RE.match(filename)
    if not match:
        return None, None, None
    return (
        match.group("source"),
        date.fromisoformat(match.group("start")),
        date.fromisoformat(match.group("end")),
    )


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    generated_chart = sa.Table(_TABLE_NAME, metadata, autoload_with=bind)

    rows = bind.execute(
        sa.select(
            generated_chart.c.id,
            generated_chart.c.file_path,
            generated_chart.c.chart_date,
            generated_chart.c.source_name,
            generated_chart.c.range_start_date,
            generated_chart.c.range_end_date,
            generated_chart.c.range_days,
        )
    ).mappings()

    for row in rows:
        parsed_source, parsed_start, parsed_end = _maybe_parse_from_file_path(row["file_path"])

        source_name = row["source_name"] or parsed_source
        range_start_date = row["range_start_date"] or parsed_start
        range_end_date = row["range_end_date"] or parsed_end or row["chart_date"]

        range_days = row["range_days"]
        if (
            range_days is None
            and range_start_date is not None
            and range_end_date is not None
            and range_end_date >= range_start_date
        ):
            range_days = (range_end_date - range_start_date).days + 1

        bind.execute(
            generated_chart.update()
            .where(generated_chart.c.id == row["id"])
            .values(
                source_name=source_name,
                range_start_date=range_start_date,
                range_end_date=range_end_date,
                range_days=range_days,
            )
        )

    columns_to_harden: list[str] = []
    for column_name in _TARGET_COLUMNS:
        null_count = bind.execute(
            sa.select(sa.func.count())
            .select_from(generated_chart)
            .where(getattr(generated_chart.c, column_name).is_(None))
        ).scalar_one()
        if null_count == 0:
            columns_to_harden.append(column_name)

    if not columns_to_harden:
        return

    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        for column_name in columns_to_harden:
            batch_op.alter_column(
                column_name,
                existing_type=generated_chart.c[column_name].type,
                nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    generated_chart = sa.Table(_TABLE_NAME, metadata, autoload_with=bind)

    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        for column_name in _TARGET_COLUMNS:
            batch_op.alter_column(
                column_name,
                existing_type=generated_chart.c[column_name].type,
                nullable=True,
            )
