from typer.testing import CliRunner

from vpn_rating_watcher.cli import app


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "VPN rating watcher CLI" in result.stdout
