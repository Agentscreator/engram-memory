import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
INSTALL_PS1 = REPO_ROOT / "install.ps1"


def run_install(home: Path, prompt_input: str = "n\n", extra_env: dict[str, str] | None = None):
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.setdefault("ENGRAM_JOIN", "ek_live_test123")
    if extra_env:
        env.update(extra_env)

    if os.name == "nt":
        return subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(INSTALL_PS1)],
            input=prompt_input,
            text=True,
            capture_output=True,
            env=env,
        )

    return subprocess.run(
        ["sh", str(INSTALL_SH)],
        input=prompt_input,
        text=True,
        capture_output=True,
        env=env,
    )


def test_install_sh_creates_cursor_config_for_fresh_install(tmp_path):
    (tmp_path / ".cursor").mkdir()

    result = run_install(tmp_path)

    assert result.returncode == 0

    config_path = tmp_path / ".cursor" / "mcp.json"
    assert config_path.exists()

    config = json.loads(config_path.read_text())
    assert config["mcpServers"]["engram"]["url"] == "https://www.engram-memory.com/mcp"


def test_install_sh_merges_with_existing_cursor_config(tmp_path):
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()

    config_path = cursor_dir / "mcp.json"
    config_path.write_text(
        json.dumps({"mcpServers": {"other": {"url": "https://example.com/mcp"}}})
    )

    result = run_install(tmp_path)

    assert result.returncode == 0

    config = json.loads(config_path.read_text())
    assert config["mcpServers"]["other"]["url"] == "https://example.com/mcp"
    assert config["mcpServers"]["engram"]["url"] == "https://www.engram-memory.com/mcp"


def test_install_sh_adds_invite_key_header(tmp_path):
    (tmp_path / ".cursor").mkdir()

    result = run_install(tmp_path, "y\nek_live_test123\n")

    assert result.returncode == 0

    config_path = tmp_path / ".cursor" / "mcp.json"
    config = json.loads(config_path.read_text())

    assert config["mcpServers"]["engram"]["headers"]["Authorization"] == "Bearer ek_live_test123"


def test_install_sh_handles_empty_existing_json_file(tmp_path):
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()

    config_path = cursor_dir / "mcp.json"
    config_path.write_text("")

    result = run_install(tmp_path)

    assert result.returncode == 0

    config = json.loads(config_path.read_text())
    assert config["mcpServers"]["engram"]["url"] == "https://www.engram-memory.com/mcp"


def test_install_sh_handles_invalid_existing_json_file(tmp_path):
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()

    config_path = cursor_dir / "mcp.json"
    config_path.write_text("{invalid json")

    result = run_install(tmp_path)

    assert result.returncode == 0

    config = json.loads(config_path.read_text())
    assert config["mcpServers"]["engram"]["url"] == "https://www.engram-memory.com/mcp"


def test_install_sh_honors_custom_mcp_url(tmp_path):
    (tmp_path / ".cursor").mkdir()

    result = run_install(
        tmp_path,
        extra_env={"ENGRAM_MCP_URL": "https://example.com/custom-mcp"},
    )

    assert result.returncode == 0

    config_path = tmp_path / ".cursor" / "mcp.json"
    config = json.loads(config_path.read_text())
    assert config["mcpServers"]["engram"]["url"] == "https://example.com/custom-mcp"
