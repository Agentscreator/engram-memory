"""Tests for the engram diagnostics commands."""

import json
import pytest
import sys
import types
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner

from engram.cli import main, _MCP_CLIENTS


_REAL_HOME = Path.home()


def _rebased_agent_clients(home: Path) -> dict:
    """Rebuild _MCP_CLIENTS with paths rooted under *home*.

    Any path that can't be made relative to _REAL_HOME (e.g. the ValidPathNotFound
    sentinel or a Windows APPDATA path on Linux) is mapped to a guaranteed
    non-existent path under home so tests stay fully isolated.
    """
    rebuilt = {}
    for name, cfg in _MCP_CLIENTS.items():
        new_cfg = dict(cfg)
        try:
            relative = cfg["path"].relative_to(_REAL_HOME)
            new_cfg["path"] = home / relative
        except ValueError:
            new_cfg["path"] = home / "_unreachable" / name
        rebuilt[name] = new_cfg
    return rebuilt


class TestVerifyCommand:
    """Tests for engram verify command."""

    @pytest.fixture
    def cli_runner(self):
        """Return a Click CLI test runner."""
        return CliRunner()

    @pytest.fixture
    def temp_home(self, tmp_path):
        """Create a temporary home directory for tests."""
        workspace_path = tmp_path / ".engram" / "workspace.json"
        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("engram.workspace.WORKSPACE_PATH", workspace_path),
            patch("engram.cli.DEFAULT_DB_PATH", tmp_path / ".engram" / "knowledge.db"),
            patch("engram.cli._MCP_CLIENTS", _rebased_agent_clients(tmp_path)),
        ):
            yield tmp_path

    def test_verify_no_workspace(self, cli_runner, temp_home):
        """Test verify when no workspace.json exists."""
        result = cli_runner.invoke(main, ["verify"])

        assert result.exit_code == 0  # Command runs, but shows failures
        assert "✗" in result.output
        assert "~/.engram/workspace.json not found" in result.output
        assert "engram init" in result.output

    def test_verify_workspace_valid_local(self, cli_runner, temp_home):
        """Test verify with valid local workspace."""
        # Create workspace.json
        workspace_dir = temp_home / ".engram"
        workspace_dir.mkdir(parents=True)
        workspace_file = workspace_dir / "workspace.json"
        workspace_file.write_text(
            json.dumps(
                {
                    "engram_id": "ENG-TEST-1234",
                    "db_url": "",  # Local mode
                    "schema": "engram",
                    "anonymous_mode": False,
                    "anon_agents": False,
                    "key_generation": 0,
                    "is_creator": True,
                }
            )
        )

        with patch("pathlib.Path.home", return_value=temp_home):
            result = cli_runner.invoke(main, ["verify"])

        assert result.exit_code == 0
        assert "✓" in result.output
        assert "workspace.json exists" in result.output
        assert "local" in result.output
        assert "SQLite storage connected" in result.output

    def test_verify_workspace_invalid_json(self, cli_runner, temp_home):
        """Test verify with invalid JSON in workspace.json."""
        workspace_dir = temp_home / ".engram"
        workspace_dir.mkdir(parents=True)
        workspace_file = workspace_dir / "workspace.json"
        workspace_file.write_text("not valid json {")

        with patch("pathlib.Path.home", return_value=temp_home):
            result = cli_runner.invoke(main, ["verify"])

        assert result.exit_code == 0
        assert "✗" in result.output
        assert "invalid JSON" in result.output

    def test_verify_no_mcp_config(self, cli_runner, temp_home):
        """Test verify when no IDE MCP configs exist."""
        # Create workspace but no IDE configs
        workspace_dir = temp_home / ".engram"
        workspace_dir.mkdir(parents=True)
        workspace_file = workspace_dir / "workspace.json"
        workspace_file.write_text(
            json.dumps(
                {
                    "engram_id": "ENG-TEST-1234",
                    "db_url": "",
                    "schema": "engram",
                }
            )
        )

        with patch("pathlib.Path.home", return_value=temp_home):
            result = cli_runner.invoke(main, ["verify"])

        assert result.exit_code == 0
        assert "✗" in result.output
        assert "not found in any IDE MCP config" in result.output

    def test_verify_engram_in_mcp_config(self, cli_runner, temp_home):
        """Test verify when Engram is configured in an IDE."""
        # Create workspace
        workspace_dir = temp_home / ".engram"
        workspace_dir.mkdir(parents=True)
        workspace_file = workspace_dir / "workspace.json"
        workspace_file.write_text(
            json.dumps(
                {
                    "engram_id": "ENG-TEST-1234",
                    "db_url": "",
                    "schema": "engram",
                }
            )
        )

        # Create Cursor MCP config with engram
        cursor_dir = temp_home / ".cursor"
        cursor_dir.mkdir(parents=True)
        mcp_config = cursor_dir / "mcp.json"
        mcp_config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "engram": {
                            "command": "uvx",
                            "args": ["--from", "engram-team@latest", "engram", "serve"],
                        }
                    }
                }
            )
        )

        with patch("pathlib.Path.home", return_value=temp_home):
            result = cli_runner.invoke(main, ["verify"])

        assert result.exit_code == 0
        assert "✓" in result.output
        assert "Cursor" in result.output

    def test_verify_detects_windsurf_config(self, cli_runner, temp_home):
        """Test verify detects Engram in Windsurf MCP config."""
        workspace_dir = temp_home / ".engram"
        workspace_dir.mkdir(parents=True)
        workspace_file = workspace_dir / "workspace.json"
        workspace_file.write_text(
            json.dumps(
                {
                    "engram_id": "ENG-TEST-1234",
                    "db_url": "",
                    "schema": "engram",
                }
            )
        )

        windsurf_dir = temp_home / ".codeium" / "windsurf"
        windsurf_dir.mkdir(parents=True)
        mcp_config = windsurf_dir / "mcp_config.json"
        mcp_config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "engram": {
                            "serverUrl": "https://www.engram-memory.com/mcp",
                        }
                    }
                }
            )
        )

        with patch("pathlib.Path.home", return_value=temp_home):
            result = cli_runner.invoke(main, ["verify"])

        assert result.exit_code == 0
        assert "✓" in result.output
        assert "Windsurf" in result.output

    def test_verify_detects_zed_config(self, cli_runner, temp_home):
        """Test verify detects Engram in Zed MCP config."""
        workspace_dir = temp_home / ".engram"
        workspace_dir.mkdir(parents=True)
        workspace_file = workspace_dir / "workspace.json"
        workspace_file.write_text(
            json.dumps(
                {
                    "engram_id": "ENG-TEST-1234",
                    "db_url": "",
                    "schema": "engram",
                }
            )
        )

        zed_dir = temp_home / ".config" / "zed"
        zed_dir.mkdir(parents=True)
        settings_file = zed_dir / "settings.json"
        settings_file.write_text(
            json.dumps(
                {
                    "context_servers": {
                        "engram": {
                            "url": "https://www.engram-memory.com/mcp",
                        }
                    }
                }
            )
        )

        with patch("pathlib.Path.home", return_value=temp_home):
            result = cli_runner.invoke(main, ["verify"])

        assert result.exit_code == 0
        assert "✓" in result.output
        assert "Zed" in result.output

    def test_verify_detects_vscode_copilot_servers_config(self, cli_runner, temp_home):
        """Test verify detects VS Code Agent Mode's servers.engram config shape."""
        workspace_dir = temp_home / ".engram"
        workspace_dir.mkdir(parents=True)
        workspace_file = workspace_dir / "workspace.json"
        workspace_file.write_text(
            json.dumps(
                {
                    "engram_id": "ENG-TEST-1234",
                    "db_url": "",
                    "schema": "engram",
                }
            )
        )

        vscode_config = _rebased_agent_clients(temp_home)["VS Code (Copilot)"]["path"]
        vscode_config.parent.mkdir(parents=True, exist_ok=True)
        vscode_config.write_text(
            json.dumps(
                {
                    "servers": {
                        "engram": {
                            "type": "http",
                            "url": "https://www.engram-memory.com/mcp",
                        }
                    }
                }
            )
        )

        with patch("pathlib.Path.home", return_value=temp_home):
            result = cli_runner.invoke(main, ["verify"])

        assert result.exit_code == 0
        assert "✓" in result.output
        assert "VS Code (Copilot)" in result.output

    def test_verify_verbose_flag(self, cli_runner, temp_home):
        """Test verify with --verbose flag shows additional details."""
        # Create workspace
        workspace_dir = temp_home / ".engram"
        workspace_dir.mkdir(parents=True)
        workspace_file = workspace_dir / "workspace.json"
        workspace_file.write_text(
            json.dumps(
                {
                    "engram_id": "ENG-TEST-1234",
                    "db_url": "",
                    "schema": "engram",
                    "anonymous_mode": True,
                }
            )
        )

        with patch("pathlib.Path.home", return_value=temp_home):
            result = cli_runner.invoke(main, ["verify", "--verbose"])

        assert result.exit_code == 0
        # Verbose should show engram_id and schema details
        assert "engram_id:" in result.output
        assert "anonymous_mode:" in result.output

    def test_doctor_runs_shared_diagnostics(self, cli_runner, temp_home):
        """Test doctor uses the same diagnostics surface as verify."""
        workspace_dir = temp_home / ".engram"
        workspace_dir.mkdir(parents=True)
        workspace_file = workspace_dir / "workspace.json"
        workspace_file.write_text(
            json.dumps(
                {
                    "engram_id": "ENG-TEST-1234",
                    "db_url": "",
                    "schema": "engram",
                }
            )
        )

        cursor_dir = temp_home / ".cursor"
        cursor_dir.mkdir(parents=True)
        mcp_config = cursor_dir / "mcp.json"
        mcp_config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "engram": {
                            "command": "uvx",
                            "args": ["--from", "engram-team@latest", "engram", "serve"],
                        }
                    }
                }
            )
        )

        result = cli_runner.invoke(main, ["doctor"])

        assert result.exit_code == 0
        assert "Engram doctor" in result.output
        assert "SQLite storage connected" in result.output
        assert "MCP server module loads" in result.output
        assert "All required checks passed" in result.output

    def test_doctor_reports_storage_failure(self, cli_runner, temp_home, monkeypatch):
        """Test doctor surfaces actionable storage failures."""
        workspace_dir = temp_home / ".engram"
        workspace_dir.mkdir(parents=True)
        workspace_file = workspace_dir / "workspace.json"
        workspace_file.write_text(
            json.dumps(
                {
                    "engram_id": "ENG-TEST-1234",
                    "db_url": "",
                    "schema": "engram",
                }
            )
        )

        async def fake_storage_check(_ws):
            return False, "PermissionError: denied"

        monkeypatch.setattr("engram.cli._check_storage_connectivity", fake_storage_check)

        result = cli_runner.invoke(main, ["doctor"])

        assert result.exit_code == 0
        assert "Storage connection failed" in result.output
        assert "PermissionError: denied" in result.output
        assert "TROUBLESHOOTING.md" in result.output

    def test_doctor_load_nli_success(self, cli_runner, temp_home, monkeypatch):
        """Test --load-nli verifies the model can be constructed."""
        workspace_dir = temp_home / ".engram"
        workspace_dir.mkdir(parents=True)
        workspace_file = workspace_dir / "workspace.json"
        workspace_file.write_text(
            json.dumps(
                {
                    "engram_id": "ENG-TEST-1234",
                    "db_url": "",
                    "schema": "engram",
                }
            )
        )

        fake_module = types.ModuleType("sentence_transformers")

        class FakeCrossEncoder:
            def __init__(self, model_name):
                self.model_name = model_name

        fake_module.CrossEncoder = FakeCrossEncoder
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        result = cli_runner.invoke(main, ["doctor", "--load-nli"])

        assert result.exit_code == 0
        assert "NLI model loaded" in result.output

    def test_verify_summary_success(self, cli_runner, temp_home):
        """Test that success summary is shown when all checks pass."""
        # Create workspace
        workspace_dir = temp_home / ".engram"
        workspace_dir.mkdir(parents=True)
        workspace_file = workspace_dir / "workspace.json"
        workspace_file.write_text(
            json.dumps(
                {
                    "engram_id": "ENG-TEST-1234",
                    "db_url": "",
                    "schema": "engram",
                }
            )
        )

        # Create Cursor MCP config with engram
        cursor_dir = temp_home / ".cursor"
        cursor_dir.mkdir(parents=True)
        mcp_config = cursor_dir / "mcp.json"
        mcp_config.write_text(
            json.dumps({"mcpServers": {"engram": {"command": "uvx", "args": ["engram", "serve"]}}})
        )

        with patch("pathlib.Path.home", return_value=temp_home):
            result = cli_runner.invoke(main, ["verify"])

        assert "All checks passed" in result.output
        assert "✓ All checks passed!" in result.output

    def test_verify_summary_failure(self, cli_runner, temp_home):
        """Test that failure summary is shown when checks fail."""
        # No workspace, no configs
        with patch("pathlib.Path.home", return_value=temp_home):
            result = cli_runner.invoke(main, ["verify"])

        assert "Some checks failed" in result.output
        assert "✗ Some checks failed" in result.output


class TestVerifyMCPClientDetection:
    """Tests for MCP client detection in verify command."""

    @pytest.fixture
    def cli_runner(self):
        return CliRunner()

    @pytest.fixture
    def temp_home(self, tmp_path):
        workspace_path = tmp_path / ".engram" / "workspace.json"
        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("engram.workspace.WORKSPACE_PATH", workspace_path),
            patch("engram.cli._MCP_CLIENTS", _rebased_agent_clients(tmp_path)),
        ):
            yield tmp_path

    def test_detects_multiple_ides(self, cli_runner, temp_home):
        """Test that verify detects engram in multiple IDE configs."""
        # Create workspace
        workspace_dir = temp_home / ".engram"
        workspace_dir.mkdir(parents=True)
        workspace_file = workspace_dir / "workspace.json"
        workspace_file.write_text(
            json.dumps(
                {
                    "engram_id": "ENG-TEST-1234",
                    "db_url": "",
                    "schema": "engram",
                }
            )
        )

        # Create multiple IDE configs with engram
        # Cursor
        cursor_dir = temp_home / ".cursor"
        cursor_dir.mkdir(parents=True)
        (cursor_dir / "mcp.json").write_text(
            json.dumps({"mcpServers": {"engram": {"command": "uvx"}}})
        )

        # VS Code
        vscode_config = _rebased_agent_clients(temp_home)["VS Code (Copilot)"]["path"]
        vscode_config.parent.mkdir(parents=True, exist_ok=True)
        vscode_config.write_text(
            json.dumps(
                {
                    "servers": {
                        "engram": {
                            "type": "http",
                            "url": "https://www.engram-memory.com/mcp",
                        }
                    }
                }
            )
        )

        with patch("pathlib.Path.home", return_value=temp_home):
            result = cli_runner.invoke(main, ["verify"])

        assert "✓" in result.output
        assert "Cursor" in result.output or "VS Code" in result.output
