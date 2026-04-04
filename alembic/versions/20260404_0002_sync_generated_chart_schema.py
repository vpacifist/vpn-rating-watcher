"""sync generated_chart schema with ORM model

Revision ID: 20260404_0002
Revises: 20260329_0001
Create Date: 2026-04-04 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260404_0002"
down_revision = "20260329_0001"
branch_labels = None
depends_on = None

_TABLE_NAME = "generated_chart"
_MISSING_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("source_name", sa.String(length=100)),
    ("range_start_date", sa.Date()),
    ("range_end_date", sa.Date()),
    ("range_days", sa.Integer()),
)


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(_TABLE_NAME)}


def upgrade() -> None:
    existing_columns = _existing_columns()
    for column_name, column_type in _MISSING_COLUMNS:
        if column_name in existing_columns:
            continue
        op.add_column(_TABLE_NAME, sa.Column(column_name, column_type, nullable=True))


def downgrade() -> None:
    existing_columns = _existing_columns()
    for column_name, _column_type in reversed(_MISSING_COLUMNS):
        if column_name not in existing_columns:
            continue
        op.drop_column(_TABLE_NAME, column_name)
