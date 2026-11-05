# Baba Is Agent

A local [Model Context Protocol](https://modelcontextprotocol.io/) server that lets an AI agent
play the **Linux Steam version of Baba Is You** using the real engine's state and rules.

**No screenshots. No OCR. No reimplemented game simulation.** A small Lua mod reports exact
objects, coordinates, conditional rules, menus, and victory events. Gameplay actions call the
engine's own movement and undo functions. An MCP-capable agent supplies the reasoning;
this project does not include a universal puzzle solver.

## Requirements

- Linux, Python **3.13+**, and [uv](https://docs.astral.sh/uv/).
- A legally installed native Linux Steam copy of Baba Is You, app **736260**.
- A game version with the global `Data/Lua/` mod loader and the documented `MF_*` Lua API.
- For menus: X11/XWayland, `libX11`, and permission to write `/dev/uinput`.
  Gameplay stepping and telemetry do **not** need a virtual keyboard.

Tested locally on GNOME Wayland with the game running through XWayland. Native Wayland-only
windows, Windows/Proton builds, and macOS are not currently supported. Other game builds,
custom mods, and all possible puzzle mechanics have not been exhaustively tested.

## Quick start

From a local clone:

```bash
uv sync --locked
uv run baba-mcp install
```

Restart the game after installing or upgrading the bridge. Then:

```bash
uv run baba-mcp doctor --live
uv run python examples/client.py get_board
```

The installer adds only our mod at `Data/Lua/zz_baba_mcp.lua` and creates a private transport
directory at `Data/Languages/baba_mcp/`. It refuses to overwrite an unrecognized mod. It does
not patch the executable, replace original Lua scripts, change unlocks, or edit save files.
**Ordinary gameplay still writes Steam saves. Back up your saves before automated play.**

If Steam uses a different library:

```bash
export BABA_GAME_DIR="/path/to/steamapps/common/Baba Is You"
uv run baba-mcp install
```

You can also use `baba-mcp --game-dir "/path/to/game" install`.

### Menu input permissions

Check `uv run baba-mcp doctor` first. If the device exists but is not writable, an administrator
can grant a temporary ACL to your desktop user:

```bash
sudo setfacl -m "u:$(id -un):rw" /dev/uinput
```

If `/dev/uinput` is absent, the administrator may need to load the `uinput` kernel module.
ACLs may need to be reapplied after reboot. Revocation:

```bash
sudo setfacl -x "u:$(id -un)" /dev/uinput
```

Do **not** run the MCP server as root or make `/dev/uinput` world-writable. This permission
allows virtual input to the desktop, not just this game. The tool requests game focus, but
focus can still be changed by the user/compositor. Do not type, switch windows, or let another
agent control the desktop while menu input is being sent.

`press` assumes the normal game bindings: arrow keys, Enter, Escape, Space, Z, and R. Custom
bindings may need to be restored in the game. Exact `act` operations do not depend on bindings.

## Connect an MCP client

Use the configuration in [`examples/mcp.json`](examples/mcp.json), replacing the absolute
project path. The server uses **stdio**, with diagnostics on stderr. Running `baba-mcp` without
a subcommand is equivalent to `baba-mcp serve`.

The client must pass `DISPLAY` and `XAUTHORITY` from the current desktop session for menu
input. Environment interpolation differs between MCP clients; `examples/client.py` explicitly
inherits the environment.

### Pi

Pi supports environment interpolation in its MCP configuration. Register from your clone:

```bash
pi mcp add baba \
  --cwd "$PWD" \
  --env 'DISPLAY=${DISPLAY}' \
  --env 'XAUTHORITY=${XAUTHORITY}' \
  --exposure direct \
  -- uv run --project "$PWD" baba-mcp
pi mcp list
```

Run `/reload` in an existing Pi session after changing external configuration. To use a
project-local registration instead, add `--local` and grant project trust when prompted.

## Tools

| Tool | Purpose |
| --- | --- |
| `get_board()` | Compact, exact board grouped by object name and effective properties. |
| `get_state(view="summary")` | Small status by default; `view="full"` requests all internal state. |
| `act(actions, view="delta")` | One engine-side batch: `"R8 U2 Z"` or a list of 1–64 actions. Only final changes are returned. |
| `press(key)` | Native keyboard input for menus, intros, and realtime/AUTO levels. |
| `choose_menu(name)` | Navigate to an enabled button reported in `state.buttons`. |
| `restart_level()` | Restart an unpaused level, discarding its current puzzle progress. |
| `list_levels(world="baba", query="", limit=30, offset=0)` | Search/paginate installed metadata; never unlock or load levels. |
| `launch_game()` | Ask Steam to launch the game; does not restart an existing instance. |

Example calls:

```bash
uv run python examples/client.py get_board
uv run python examples/client.py act '{"actions": "R8 U2 Z"}'
uv run python examples/client.py choose_menu '{"name": "resume"}'
```

### Efficient agent use

Read `get_board` once, then send a complete planned route in one `act` call. Compact notation:
`U/D/L/R` move, `W` waits, `Z` undoes; optional counts repeat an action (`R8`, `U2`).
Each batch advances through native game frames, checks stop conditions after each move, and
produces **one final snapshot** rather than reading/serializing the whole board after every move.
Older installed bridges remain supported with a slower compatibility path until reinstalled.

Action and menu tools return deltas by default: changed units/rules/buttons only. Delta units
are `[id, name, x, y, direction, properties]`; `removed` lists deleted IDs. Unmentioned state is
unchanged. A `refresh: "get_board"` reply means the agent needs to read the new scene.
`view="summary"`, `view="board"`, and `view="full"` are explicit alternatives. Do not request
full state after every move. Replies use one minified JSON text block, without a duplicate
`structuredContent` payload; the example client decodes it.

After upgrading the bridge, restart the game. After changing server code, reconnect/reload
the MCP client so it sees the new tools and defaults.

### State and action semantics

- Coordinates start at zero. Directions: **right = 0, up = 1, left = 2, down = 3**.
- `get_board().objects[*].at` contains `[x, y, direction, unit_id]` entries. Boards include
  a format legend; essential instructions are also in tool descriptions, not just server instructions.
- Every reply includes `phase`, `ready`, `controller`, current `controlled` positions,
  `no_player`, `can_undo`, and a `recovery_hint` when appropriate. These fields are snapshots,
  even in delta mode. `controller="special"` flags parsed LEVEL/EMPTY IS YOU rules; conditions
  may still prevent control. `no_player=1` alone does not imply death on maps or special levels.
- Action replies include `requested`, `executed`, `stop_reason`, and `board_changed`.
  `executed` counts processed commands, including blocked moves, not successful displacement.
  `board_changed` compares visible objects, rules, dimensions, and scene, not hidden engine state.
  A stop reason of `control_lost` calls for undo/recovery, not further direction commands.
- If the engine reports no player and there is no ordinary controller, `act` does not send
  directions/waits: it returns `executed=0` and recovery guidance. Map cursors, parsed
  LEVEL/EMPTY IS YOU rules, and AUTO are exempt. This guard is not a universal death detector.
  Start a recovery sequence with `Z`, or call `restart_level`. A leading undo run is verified
  before subsequent directions; native recovery-plus-travel may use two engine batches.
- `rules` contains parsed word triples and their conditions. Do not treat every parsed rule
  as unconditional. `properties` reports common checked effects, not every property in the game.
- `act` uses `command()`, `undo()`, `code()`, and `MF_update()` inside the real game.
  It stops early on victory, player death, level transition, pause, or other menu changes.
  Maps with a SELECT cursor do not stop merely because they have no YOU object.
- `undo_depth` is the engine's undo buffer depth; `turns` counts turn-end hooks, including
  native updates associated with undo. It is not necessarily a puzzle's official move counter.
- `won` describes the current victory event; `wins` counts victory hooks since this bridge
  instance started. Neither is a count of newly unlocked levels or total saved completions.
- During transitions, metadata may already refer to the next level while units still refer
  to the previous scene. Read fresh state after the transition before planning more moves.
- AUTO/realtime levels require `press`; they are not deterministic single-step `act` sessions.
- A request timeout does not prove a move failed. **Inspect fresh state before retrying**.
  Mutating requests are never automatically retried, and pending request files are removed.

## Architecture

```text
MCP client → stdio server → typed game service → serialized request/ack transport
                                               ↓
                         official Lua mod hooks → native engine functions
                                               ↓
                            native INI telemetry → validated game state
```

The game's sandbox does not expose Lua `io` or `os`. Requests are fixed, allowlisted Lua data
tables loaded with the engine's existing `dofile`. Responses use `MF_setfile` / `MF_store` in an
isolated INI. The bridge temporarily redirects the native language storage slot and restores
`lang_<language>.txt` immediately afterwards; it does not modify language files. Mods that
replace the language storage mechanism may be incompatible.

Request IDs prevent duplicate dispatch within the running bridge. Atomic request replacement,
strict response validation, and a bounded cross-process lock protect cooperating clients.
Do not run concurrent controllers using different `BABA_BRIDGE_DIR` values for the same game.

```text
src/baba_is_agent/
  assets/bridge.lua   Game-side adapter (shipped in the wheel)
  config.py          Paths and configuration
  models.py          Validated native state and typed actions
  storage.py         Atomic writes and process locks
  transport.py       Request/acknowledgement protocol
  input.py           Linux uinput and XWayland activation
  installer.py       Reversible installation
  service.py         Gameplay and menu operations
  server.py          MCP tool registration
  cli.py             CLI and diagnostics
```

## Configuration

| Variable | Default / meaning |
| --- | --- |
| `BABA_GAME_DIR` | Auto-detect the usual Steam install under `~/.local/share/Steam` or `~/.steam/steam`. |
| `BABA_BRIDGE_DIR` | Lock directory, default `$XDG_STATE_HOME/baba-mcp` or `~/.local/state/baba-mcp`. |
| `DISPLAY`, `XAUTHORITY` | Current X11/XWayland session, used only for menu focus. |

Requests and responses always live under the game's `Data/Languages/baba_mcp/` directory;
`BABA_BRIDGE_DIR` changes only local coordination storage.

## Development

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest --cov=baba_is_agent
lua tests/test_bridge.lua src/baba_is_agent/assets/bridge.lua
uv build
```

Python tests use temporary files, mocked input, and a real MCP stdio subprocess. They do not
need Steam, a running game, desktop access, or elevated privileges. The Lua test runs the bridge
with `io` and `os` removed and checks dispatch deduplication, undo, and error containment.
GitHub Actions runs these checks and verifies that the built wheel includes the Lua asset.

An explicitly opt-in live smoke check (read-only):

```bash
uv run python scripts/verify_live.py
```

Ruff uses the repository's Python 3.13 target and 99-character line length. To apply fixes:

```bash
uv run ruff check --fix .
uv run ruff format .
```

## Uninstall

```bash
uv run baba-mcp uninstall
```

Restart the game afterwards. This removes only recognized bridge files, not saves or other
mods. Remove the MCP client registration separately (`pi mcp remove baba` for Pi).

## Security and licensing

This is a **local, trusted-client** integration, not a remote-control service. There is no HTTP
listener, authentication layer, or arbitrary Lua-evaluation MCP tool. A process running as the
same desktop user can still tamper with bridge files, and native input is desktop-wide.
Only expose these tools to trusted local agents; do not publish the transport directory.

Project code is licensed under [MIT](LICENSE). Baba Is You, its executable, scripts, levels,
artwork, and trademarks belong to their respective owners and are **not** included or
relicensed by this repository. This is an unofficial project, not affiliated with the game's
creators or Steam.
