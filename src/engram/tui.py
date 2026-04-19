"""Claude Code-style full-screen interactive TUI for Engram."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.layout.screen import Point
from prompt_toolkit.styles import Style

_VERSION = "0.1.1"

_STYLE = Style.from_dict(
    {
        "header.title": "bold noinherit #ffffff",
        "header.version": "noinherit #555555",
        "header.mode": "bold noinherit #00dd55",
        "header.id": "noinherit #555555",
        "header.cwd": "noinherit #555555",
        "header.tagline": "noinherit #ff8800",
        "header.logo": "bold noinherit #00dd55",
        "separator": "noinherit #333333",
        "prompt": "bold noinherit #00dd55",
        "output": "noinherit #cccccc",
        "output.cmd": "bold noinherit #00dd55",
        "output.error": "noinherit #ff5555",
        "output.dim": "noinherit #555555",
        "toolbar": "noinherit bg:#111111 #444444",
        "toolbar.key": "noinherit bg:#111111 #00dd55",
        "toolbar.sep": "noinherit bg:#111111 #333333",
    }
)

_VALID_COMMANDS = {
    "conflicts",
    "resolve",
    "search",
    "status",
    "whoami",
    "export",
    "info",
    "stats",
    "verify",
    "doctor",
}

_HELP_LINES: list[tuple[str, str]] = [
    ("class:output.dim", "\n"),
    ("class:output", "  Commands:\n"),
    ("class:output", "    resolve <id> <resolution>  — resolve a conflict\n"),
    ("class:output", "    conflicts                  — refresh conflicts\n"),
    ("class:output", "    clear                      — clear output  (Ctrl+L)\n"),
    ("class:output", "    quit / q                   — exit          (Ctrl+C)\n"),
    ("class:output.dim", "\n"),
]


def run_tui(ws: Any, ctx: Any) -> None:
    """Launch the Claude Code-style interactive shell."""
    if ws.server_url and not ws.db_url:
        mode_label = "hosted"
    elif ws.db_url:
        mode_label = "team · PostgreSQL"
    else:
        mode_label = "local · SQLite"

    workspace_id = ws.engram_id or "-"
    try:
        rel = os.path.relpath(os.getcwd(), os.path.expanduser("~"))
        cwd = "~/" + rel if not rel.startswith("..") else os.getcwd()
    except ValueError:
        cwd = os.getcwd()

    # Mutable state
    state: dict[str, Any] = {}
    output_lines: list[tuple[str, str]] = []

    # ── formatted text producers ──────────────────────────────────────────

    _LOGO_OPEN = [
        "  ▄████▄  ",
        " ██▄██▄██ ",
        " ███▀▀███ ",
        " ▀ ▀  ▀ ▀ ",
    ]
    _LOGO_CLOSED = [
        "  ▄████▄  ",
        " ████████ ",
        " ███▀▀███ ",
        " ▀ ▀  ▀ ▀ ",
    ]

    def header_text() -> AnyFormattedText:
        logo = _LOGO_OPEN if state.get("eyes", "open") == "open" else _LOGO_CLOSED
        lines = [
            [
                ("class:header.logo", logo[0]),
                ("class:header.title", "   Engram "),
                ("class:header.version", f"v{_VERSION}"),
            ],
            [
                ("class:header.logo", logo[1]),
                ("class:header.mode", f"   {mode_label} "),
                ("class:header.id", f"· {workspace_id}"),
            ],
            [("class:header.logo", logo[2]), ("class:header.cwd", f"   {cwd}")],
            [
                ("class:header.logo", logo[3]),
                ("class:header.tagline", "   Shared memory for AI agents"),
            ],
        ]

        result: list[tuple[str, str]] = []
        for line in lines:
            result.extend(line)
            result.append(("", "\n"))
        return result

    def separator_text() -> AnyFormattedText:
        return [("class:separator", "─" * 200)]

    def output_text() -> AnyFormattedText:
        return list(output_lines)

    def output_cursor_pos() -> Point:
        total = sum(t.count("\n") for _, t in output_lines)
        return Point(x=0, y=max(0, total - 1))

    def toolbar_text() -> AnyFormattedText:
        return [
            ("class:toolbar", "  type "),
            ("class:toolbar.key", "resolve <id> <resolution>"),
            ("class:toolbar", " to settle a conflict"),
            ("class:toolbar.sep", "   ·   "),
            ("class:toolbar.key", "?"),
            ("class:toolbar", " help"),
            ("class:toolbar.sep", "   ·   "),
            ("class:toolbar.key", "Ctrl+C"),
            ("class:toolbar", " quit"),
            ("class:toolbar", "  "),
        ]

    # ── input & key handling ──────────────────────────────────────────────

    input_buf = Buffer(name="main_input", multiline=False)

    def run_cmd(cmd: str, arg: str, app: Application) -> None:
        output_lines.append(("class:output.cmd", f"\n  > {cmd}{' ' + arg if arg else ''}\n"))
        _run_engram_command(cmd, arg, output_lines)
        app.invalidate()

    def handle_command(text: str, app: Application) -> None:
        text = text.strip()
        if not text:
            return

        output_lines.append(("class:output.cmd", f"\n  > {text}\n"))
        parts = text.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("quit", "exit", "q"):
            app.exit()
            return
        if cmd in ("?", "help"):
            output_lines.extend(_HELP_LINES)
            return
        if cmd == "clear":
            output_lines.clear()
            return
        if cmd not in _VALID_COMMANDS:
            output_lines.append(
                ("class:output.error", f"  Unknown command: {cmd}. Type ? for help.\n")
            )
            return

        if cmd == "search" and not arg:
            output_lines.append(("class:output.error", "  Usage: search <query>\n"))
            return

        _run_engram_command(cmd, arg, output_lines)

    kb = KeyBindings()

    @kb.add("enter")
    def _enter(event: Any) -> None:
        text = input_buf.text
        input_buf.reset()
        handle_command(text, event.app)

    @kb.add("c-c")
    @kb.add("c-d")
    def _exit(event: Any) -> None:
        event.app.exit()

    @kb.add("c-l")
    def _clear(event: Any) -> None:
        output_lines.clear()
        event.app.invalidate()

    # ── layout ────────────────────────────────────────────────────────────
    #
    # Order (top → bottom):
    #   Header      (fixed 4 lines)
    #   Separator   (fixed 1 line)
    #   Output area (flexible — conflicts on startup, fills with output)
    #   Separator   (fixed 1 line)
    #   Input bar   (fixed 1 line)
    #   Toolbar     (fixed 1 line)

    layout = Layout(
        HSplit(
            [
                Window(
                    FormattedTextControl(header_text, focusable=False),
                    height=D.exact(4),
                    dont_extend_height=True,
                ),
                Window(
                    FormattedTextControl(separator_text, focusable=False),
                    height=D.exact(1),
                    dont_extend_height=True,
                ),
                Window(),  # pushes output down toward input
                Window(
                    FormattedTextControl(
                        output_text,
                        get_cursor_position=output_cursor_pos,
                        focusable=False,
                    ),
                    wrap_lines=True,
                    dont_extend_height=True,
                ),
                Window(
                    FormattedTextControl(separator_text, focusable=False),
                    height=D.exact(1),
                    dont_extend_height=True,
                ),
                Window(
                    BufferControl(
                        buffer=input_buf,
                        input_processors=[BeforeInput("> ", style="class:prompt")],
                    ),
                    height=D.exact(1),
                    dont_extend_height=True,
                ),
                Window(
                    FormattedTextControl(toolbar_text, focusable=False),
                    height=D.exact(1),
                    dont_extend_height=True,
                    style="class:toolbar",
                ),
            ]
        ),
        focused_element=input_buf,
    )

    app = Application(
        layout=layout,
        style=_STYLE,
        key_bindings=kb,
        full_screen=True,
        cursor=CursorShape.BLINKING_BLOCK,
        mouse_support=False,
    )

    import threading
    import time

    def _blink() -> None:
        while True:
            time.sleep(3)
            state["eyes"] = "closed"
            app.invalidate()
            time.sleep(0.15)
            state["eyes"] = "open"
            app.invalidate()

    threading.Thread(target=_blink, daemon=True).start()

    # Load conflicts immediately on startup
    _run_engram_command("conflicts", "", output_lines)

    app.run()


# ── command runner ─────────────────────────────────────────────────────


def _run_engram_command(cmd: str, arg: str, output_lines: list[tuple[str, str]]) -> None:
    engram_bin = _find_engram_bin()
    cli_args = [engram_bin, cmd]
    if arg:
        cli_args.extend(arg.split())

    try:
        result = subprocess.run(cli_args, capture_output=True, text=True, timeout=30)
        combined = (result.stdout + result.stderr).strip()
        if combined in ("[]", "{}", ""):
            output_lines.append(("class:output.dim", f"  No {cmd} found.\n"))
        elif combined:
            err = result.returncode != 0
            for line in combined.splitlines():
                style = "class:output.error" if err else "class:output"
                output_lines.append((style, f"  {line}\n"))
        else:
            output_lines.append(("class:output.dim", f"  No output from {cmd}.\n"))
    except subprocess.TimeoutExpired:
        output_lines.append(("class:output.error", "  Command timed out after 30s\n"))
    except FileNotFoundError:
        output_lines.append(("class:output.error", f"  Could not find: {engram_bin}\n"))
    except Exception as e:
        output_lines.append(("class:output.error", f"  Error: {e}\n"))


def _find_engram_bin() -> str:
    argv0 = sys.argv[0]
    if os.path.isfile(argv0) and os.access(argv0, os.X_OK):
        return argv0
    return "engram"
