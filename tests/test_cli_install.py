import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from engram.cli import main, _MCP_CLIENTS, _engram_mcp_entry_for_client


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

    monkeypatch.setenv("ENGRAM_MCP_URL", "https://www.engram-memory.com/mcp")

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
        assert data["mcpServers"]["engram"] == {"serverUrl": "https://www.engram-memory.com/mcp"}


def test_install_writes_zed_context_server_url(tmp_path, monkeypatch):
    runner = CliRunner()
    workspace_path = tmp_path / ".engram" / "workspace.json"

    monkeypatch.setenv("ENGRAM_MCP_URL", "https://www.engram-memory.com/mcp")

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
        assert data["context_servers"]["engram"] == {"url": "https://www.engram-memory.com/mcp"}


def test_cursor_mcp_entry_uses_remote_url(monkeypatch):
    monkeypatch.setenv("ENGRAM_MCP_URL", "https://www.engram-memory.com/mcp")

    assert _engram_mcp_entry_for_client("Cursor") == {"url": "https://www.engram-memory.com/mcp"}


def test_install_writes_cursor_remote_mcp_url(tmp_path, monkeypatch):
    runner = CliRunner()
    workspace_path = tmp_path / ".engram" / "workspace.json"

    monkeypatch.setenv("ENGRAM_MCP_URL", "https://www.engram-memory.com/mcp")

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("engram.workspace.WORKSPACE_PATH", workspace_path),
        patch("engram.cli._MCP_CLIENTS", _rebased_mcp_clients(tmp_path)),
    ):
        cursor_config = tmp_path / ".cursor" / "mcp.json"
        cursor_config.parent.mkdir(parents=True, exist_ok=True)
        cursor_config.write_text("{}")

        result = runner.invoke(main, ["install"])

        assert result.exit_code == 0

        data = json.loads(cursor_config.read_text())
        assert "mcpServers" in data
        assert "engram" in data["mcpServers"]
        assert data["mcpServers"]["engram"] == {"url": "https://www.engram-memory.com/mcp"}


def test_install_migrates_legacy_cursor_stdio_entry(tmp_path, monkeypatch):
    runner = CliRunner()
    workspace_path = tmp_path / ".engram" / "workspace.json"

    monkeypatch.setenv("ENGRAM_MCP_URL", "https://www.engram-memory.com/mcp")

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("engram.workspace.WORKSPACE_PATH", workspace_path),
        patch("engram.cli._MCP_CLIENTS", _rebased_mcp_clients(tmp_path)),
    ):
        cursor_config = tmp_path / ".cursor" / "mcp.json"
        cursor_config.parent.mkdir(parents=True, exist_ok=True)
        cursor_config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "engram": {
                            "command": "uvx",
                            "args": ["--from", "engram-team@latest", "engram", "serve"],
                        },
                        "other": {"url": "https://example.com/mcp"},
                    }
                }
            )
        )

        result = runner.invoke(main, ["install"])

        assert result.exit_code == 0

        data = json.loads(cursor_config.read_text())
        assert data["mcpServers"]["engram"] == {"url": "https://www.engram-memory.com/mcp"}
        assert data["mcpServers"]["other"] == {"url": "https://example.com/mcp"}


def test_install_preserves_custom_cursor_entry(tmp_path, monkeypatch):
    runner = CliRunner()
    workspace_path = tmp_path / ".engram" / "workspace.json"

    monkeypatch.setenv("ENGRAM_MCP_URL", "https://www.engram-memory.com/mcp")

    custom_entry = {
        "command": "uvx",
        "args": ["--from", "engram-team@dev", "engram", "serve"],
    }

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("engram.workspace.WORKSPACE_PATH", workspace_path),
        patch("engram.cli._MCP_CLIENTS", _rebased_mcp_clients(tmp_path)),
    ):
        cursor_config = tmp_path / ".cursor" / "mcp.json"
        cursor_config.parent.mkdir(parents=True, exist_ok=True)
        cursor_config.write_text(json.dumps({"mcpServers": {"engram": custom_entry}}))

        result = runner.invoke(main, ["install"])

        assert result.exit_code == 0

        data = json.loads(cursor_config.read_text())
        assert data["mcpServers"]["engram"] == custom_entry


def test_install_writes_vscode_copilot_http_server(tmp_path, monkeypatch):
    runner = CliRunner()
    workspace_path = tmp_path / ".engram" / "workspace.json"
    rebased = _rebased_mcp_clients(tmp_path)

    monkeypatch.setenv("ENGRAM_MCP_URL", "https://www.engram-memory.com/mcp")

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("engram.workspace.WORKSPACE_PATH", workspace_path),
        patch("engram.cli._MCP_CLIENTS", rebased),
    ):
        config_path = rebased["VS Code (Copilot)"]["path"]
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("{}")

        result = runner.invoke(main, ["install"])

        assert result.exit_code == 0

        data = json.loads(config_path.read_text())
        assert "servers" in data
        assert "engram" in data["servers"]
        assert data["servers"]["engram"] == {
            "type": "http",
            "url": "https://www.engram-memory.com/mcp",
        }


def test_install_writes_git_pre_commit_hook(tmp_path, monkeypatch):
    runner = CliRunner()
    project = tmp_path / "repo"
    hook_dir = project / ".git" / "hooks"
    hook_dir.mkdir(parents=True)
    workspace_path = tmp_path / ".engram" / "workspace.json"

    monkeypatch.chdir(project)

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("engram.workspace.WORKSPACE_PATH", workspace_path),
        patch("engram.cli._MCP_CLIENTS", {}),
        patch("engram.cli._try_claude_code_cli", lambda *args, **kwargs: None),
        patch("engram.cli._write_claude_code_hook", return_value=False),
        patch("engram.cli._write_windsurf_hook", return_value=False),
        patch("engram.cli._write_cursor_hook", return_value=False),
        patch("engram.cli._write_kiro_hook", return_value=False),
        patch("engram.cli._write_project_claude_mcp_config", return_value=False),
    ):
        result = runner.invoke(main, ["install"])

    hook_path = hook_dir / "pre-commit"
    assert result.exit_code == 0
    assert hook_path.exists()
    assert 'engram pre-commit-hook "$@"' in hook_path.read_text()
