import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from engram.cli import main, _MCP_CLIENTS


_REAL_HOME = Path.home()


def _rebased_mcp_clients(home: Path) -> dict:
    rebuilt = {}
    for name, cfg in _MCP_CLIENTS.items():
        new_cfg = dict(cfg)
        try:
            relative = cfg["path"].relative_to(_REAL_HOME)
            new_cfg["path"] = home / relative
        except ValueError:
            pass
        rebuilt[name] = new_cfg
    return rebuilt


def test_install_writes_windsurf_server_url(tmp_path, monkeypatch):
    runner = CliRunner()
    workspace_path = tmp_path / ".engram" / "workspace.json"

    monkeypatch.setenv("ENGRAM_MCP_URL", "https://mcp.engram.app/mcp")

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("engram.workspace.WORKSPACE_PATH", workspace_path),
        patch("engram.cli._MCP_CLIENTS", _rebased_mcp_clients(tmp_path)),
    ):
        windsurf_config = tmp_path / ".codeium" / "windsurf" / "mcp_config.json"
        windsurf_config.parent.mkdir(parents=True, exist_ok=True)
        windsurf_config.write_text("{}")

        result = runner.invoke(main, ["install"])

        assert result.exit_code == 0

        data = json.loads(windsurf_config.read_text())
        assert "mcpServers" in data
        assert "engram" in data["mcpServers"]
        assert data["mcpServers"]["engram"] == {"serverUrl": "https://mcp.engram.app/mcp"}


def test_install_writes_zed_context_server_url(tmp_path, monkeypatch):
    runner = CliRunner()
    workspace_path = tmp_path / ".engram" / "workspace.json"

    monkeypatch.setenv("ENGRAM_MCP_URL", "https://mcp.engram.app/mcp")

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("engram.workspace.WORKSPACE_PATH", workspace_path),
        patch("engram.cli._MCP_CLIENTS", _rebased_mcp_clients(tmp_path)),
    ):
        zed_config = tmp_path / ".config" / "zed" / "settings.json"
        zed_config.parent.mkdir(parents=True, exist_ok=True)
        zed_config.write_text("{}")

        result = runner.invoke(main, ["install"])

        assert result.exit_code == 0

        data = json.loads(zed_config.read_text())
        assert "context_servers" in data
        assert "engram" in data["context_servers"]
        assert data["context_servers"]["engram"] == {"url": "https://mcp.engram.app/mcp"}
