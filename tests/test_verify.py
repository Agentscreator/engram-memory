"""Tests for the engram verify command."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner

from engram.cli import main, _MCP_CLIENTS


_REAL_HOME = Path.home()


def _rebased_agent_clients(home: Path) -> dict:
    """Rebuild _AGENT_CLIENTS with paths rooted under *home*."""
    rebuilt = {}
    for name, cfg in _MCP_CLIENTS.items():
        new_cfg = dict(cfg)
        try:
            relative = cfg["path"].relative_to(_REAL_HOME)
            new_cfg["path"] = home / relative
        except ValueError:
            pass  # non-home paths (XDG etc.) — leave as-is
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
                            "serverUrl": "https://mcp.engram.app/mcp",
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
                            "url": "https://mcp.engram.app/mcp",
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
        vscode_dir = temp_home / ".vscode"
        vscode_dir.mkdir(parents=True)
        (vscode_dir / "mcp.json").write_text(
            json.dumps({"mcpServers": {"engram": {"command": "uvx"}}})
        )

        with patch("pathlib.Path.home", return_value=temp_home):
            result = cli_runner.invoke(main, ["verify"])

        assert "✓" in result.output
        assert "Cursor" in result.output or "VS Code" in result.output
