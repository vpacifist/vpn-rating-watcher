from __future__ import annotations

from datetime import date
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from alembic import command
from vpn_rating_watcher.core.settings import get_settings
from vpn_rating_watcher.db.models import GeneratedChart


def test_fresh_alembic_schema_supports_generated_chart_model(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "fresh_from_alembic.sqlite"
    database_url = f"sqlite+pysqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    repo_root = Path(__file__).resolve().parents[1]
    alembic_cfg = Config(str(repo_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(repo_root / "alembic"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(database_url, future=True)
    columns = {column["name"]: column for column in inspect(engine).get_columns("generated_chart")}
    assert columns["source_name"]["nullable"] is False
    assert columns["range_start_date"]["nullable"] is False
    assert columns["range_end_date"]["nullable"] is False
    assert columns["range_days"]["nullable"] is False

    with Session(engine) as session:
        session.add(
            GeneratedChart(
                chart_date=date(2026, 4, 4),
                chart_type="historical_line_chart",
                source_name="maximkatz",
                range_start_date=date(2026, 4, 1),
                range_end_date=date(2026, 4, 4),
                range_days=4,
                file_path="artifacts/charts/test.png",
            )
        )
        session.commit()

        persisted = session.execute(select(GeneratedChart)).scalar_one()

    assert persisted.source_name == "maximkatz"
    assert persisted.range_start_date == date(2026, 4, 1)
    assert persisted.range_end_date == date(2026, 4, 4)
    assert persisted.range_days == 4
