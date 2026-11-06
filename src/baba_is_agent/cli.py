"""CLI entry point; stdout is reserved for MCP while serving."""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from baba_is_agent import __version__
from baba_is_agent.config import Settings
from baba_is_agent.errors import BabaError
from baba_is_agent.installer import bridge_source, install, uninstall
from baba_is_agent.models import JsonObject
from baba_is_agent.server import create_server
from baba_is_agent.service import GameService


def diagnose(settings: Settings, *, live: bool = False) -> JsonObject:
    """Inspect prerequisites without granting privileges or restarting anything."""
    installed = settings.mod_path.is_file()
    report: JsonObject = {
        "version": __version__,
        "platform": sys.platform,
        "game_dir": str(settings.game_dir),
        "game_found": (settings.game_dir / "Data/modsupport.lua").is_file(),
        "mod_installed": installed,
        "mod_matches_package": installed
        and settings.mod_path.read_text(encoding="utf-8") == bridge_source(),
        "transport_dir": str(settings.transport_dir),
        "uinput_writable": os.access("/dev/uinput", os.W_OK),
        "display_configured": bool(os.environ.get("DISPLAY")),
        "xauthority_configured": bool(os.environ.get("XAUTHORITY")),
    }
    if live:
        service = GameService(settings)
        try:
            state = service.get_state()
            report["live"] = {"frame": state.frame, "level": state.level, "menu": state.menu}
        finally:
            service.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Native-state MCP for Baba Is You on Linux.")
    parser.add_argument("--version", action="version", version=f"baba-is-agent {__version__}")
    parser.add_argument("--game-dir", type=Path, help="Override BABA_GAME_DIR")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="Serve MCP on stdio (default)")
    commands.add_parser(
        "install", help="Install the reversible Lua bridge; restart game afterwards"
    )
    commands.add_parser("uninstall", help="Remove our bridge; do not touch saves")
    doctor = commands.add_parser("doctor", help="Inspect local prerequisites")
    doctor.add_argument("--live", action="store_true", help="Also request native game telemetry")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.game_dir is not None:
        from dataclasses import replace

        settings = replace(settings, game_dir=args.game_dir)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    try:
        if args.command == "install":
            print(json.dumps(install(settings), indent=2))
        elif args.command == "uninstall":
            print(json.dumps(uninstall(settings), indent=2))
        elif args.command == "doctor":
            print(json.dumps(diagnose(settings, live=args.live), indent=2))
        else:
            if sys.platform != "linux":
                raise BabaError("The native game bridge currently supports Linux only")
            service = GameService(settings)
            try:
                create_server(service).run(transport="stdio")
            finally:
                service.close()
    except (BabaError, OSError, ValueError) as error:
        print(f"baba-mcp: {error}", file=sys.stderr)
        return 1
    return 0
