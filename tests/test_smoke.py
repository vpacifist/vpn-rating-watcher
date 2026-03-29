import importlib
import sys

from typer.testing import CliRunner


def _import_cli_module():
    return importlib.import_module("vpn_rating_watcher.cli")


def test_cli_import_without_database_url(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sys.modules.pop("vpn_rating_watcher.cli", None)
    module = _import_cli_module()
    assert module.app is not None


def test_cli_help() -> None:
    runner = CliRunner()
    sys.modules.pop("vpn_rating_watcher.cli", None)
    module = _import_cli_module()
    result = runner.invoke(module.app, ["--help"])
    assert result.exit_code == 0
    assert "VPN rating watcher CLI" in result.stdout
