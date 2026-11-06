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

Complete [Quick start](#quick-start) first: client registration does not install the game-side
bridge. Run the commands below **from the clone's root directory**, with `uv` on `PATH`.
`"$PWD"` is saved as an absolute path, so keep the clone at that location.

Start the client as your normal desktop user on the same machine as the game. The server
needs the current desktop session's `DISPLAY` and, where used, `XAUTHORITY` for menu input.
If you set `BABA_GAME_DIR`, make sure the client passes it to the server as well.
Environment interpolation differs between clients; `examples/client.py` explicitly inherits
the environment. Connect any of these clients, but do not let them control the game concurrently.

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
User configuration lives in `~/.pi/agent/mcp.json`; project configuration in `.pi/mcp.json`.
`--exposure direct` makes the game tools available without a tool-search step.

See the [Pi MCP documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/mcp.md).
These commands require a Pi version with built-in `pi mcp` support.

### Codex CLI

Register the local stdio server:

```bash
codex mcp add baba \
  --env "DISPLAY=${DISPLAY}" \
  --env "XAUTHORITY=${XAUTHORITY:-}" \
  -- uv run --project "$PWD" baba-mcp
codex mcp list
```

Restart an existing Codex session after changing configuration; use `/mcp` inside Codex to
inspect the connection. The CLI saves the entry in `~/.codex/config.toml`.

The command above saves the **current values** of the desktop variables. To forward fresh
values whenever Codex starts, remove those two entries from `[mcp_servers.baba.env]` and add
this field to the existing `[mcp_servers.baba]` table instead:

```toml
env_vars = ["DISPLAY", "XAUTHORITY"]
```

For project-only configuration, put the server's TOML tables in `.codex/config.toml` instead;
Codex reads project configuration only in trusted projects. Add `BABA_GAME_DIR` to `env_vars`
if needed. See the [Codex MCP documentation](https://developers.openai.com/codex/mcp/).

### Claude Code

Register for your user account (available across projects):

```bash
claude mcp add --transport stdio --scope user \
  --env "DISPLAY=${DISPLAY}" \
  --env "XAUTHORITY=${XAUTHORITY:-}" \
  baba -- uv run --project "$PWD" baba-mcp
claude mcp get baba
```

Restart an existing Claude Code session, then use `/mcp` to inspect the connection and approve
tool use when prompted. User-scoped servers are stored in `~/.claude.json`.

The command saves the **current values** of the desktop variables; update them if your desktop
session changes. For a shared project registration, replace `--scope user` with `--scope project`:
this writes `.mcp.json`, and Claude Code asks for approval before using its servers. The saved
clone path and desktop values are machine-specific; review them before sharing that file.
For a private registration limited to the current project, use `--scope local` instead.
See the [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).

### Verify the connection

With the game running and the bridge installed, ask the agent to call `baba.get_board` (the
client may display a prefix such as `mcp__baba__get_board`). It should return the current board
and rules. A successful MCP connection alone does not prove the game bridge or menu input
permissions work; use `uv run baba-mcp doctor --live` to diagnose those separately.

## Tools

| Tool | Purpose |
| --- | --- |
| `get_board()` | Compact, exact board grouped by object name and effective properties. |
| `get_state(view="summary")` | Small status by default; `view="full"` requests all internal state. |
| `enter_level(number)` | Enter an accessible regular numbered level on the current map using native cursor travel and confirmation. |
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

### Simplified tool profile

For smaller models, start the server with `baba-mcp --profile lite serve` or set
`BABA_MCP_PROFILE=lite` in the MCP server environment. Reconnect the client after switching.
The default `expert` profile preserves the existing API.

Lite exposes only `observe()`, `move(direction, steps=1)`, `undo(steps=1)`, `restart()`,
`press(key)`, and `enter_level(number)`. There is no `view` parameter or compact command language to learn.
Each action returns a self-contained grid and objects with named positions (`x`, `y`,
`direction`, `id`); `observe()` reads without advancing time. Grid cells are space-separated:
uppercase words, lowercase objects, `+` for stacks, `.` for empty. Inert objects and rule
conditions are preserved. `changes_since_previous_reply` highlights transformations and
property changes; for example, a key with OPEN but not PUSH is not implicitly pushable.
For example: `move(direction="right", steps=4)`. Keep unrelated MCP servers out of the
client's gaming tool set; the server cannot hide another server's tools.

On a map, `observe()` (lite) and `get_board()` (expert) also include `map.levels`:
local number, style, name, file, coordinates, and availability from live completion state.
`enter_level(number=6)` enters regular level 06 on that map. It plans at most 64 cursor
moves over native accessible cells, checks the actual destination before confirming,
and dismisses the level introduction once. It never loads a file directly or unlocks a level.
Letter/extra levels and unusual map mechanics still require manual cursor movement.
Missing numbering metadata is reported alongside the board, not instead of it.

### Efficient agent use

Read `get_board` once, then send a complete planned route in one `act` call. Compact notation:
`U/D/L/R` move, `W` waits, `Z` undoes; optional counts repeat an action (`R8`, `U2`).
Full names also work (`"right up undo"`, `"down"`, `"wait"`), as do actual JSON arrays
(`{"actions":["right","up"]}`). Do not serialize the array into a string or mix full names
with compact commands. Invalid input is rejected before any gameplay request; errors include
concrete corrections. The published schema includes action and pagination limits.
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
mods. Remove the MCP client registration separately:

```bash
pi mcp remove baba
codex mcp remove baba
claude mcp remove --scope user baba
```

Run only the command for the client you configured. For project-local Pi registration, add
`--local`; for Claude Code, use the same `--scope` you used when adding the server. If you
configured Codex by editing a TOML file, remove its `[mcp_servers.baba]` tables from that file.

## Security and licensing

This is a **local, trusted-client** integration, not a remote-control service. There is no HTTP
listener, authentication layer, or arbitrary Lua-evaluation MCP tool. A process running as the
same desktop user can still tamper with bridge files, and native input is desktop-wide.
Only expose these tools to trusted local agents; do not publish the transport directory.

Project code is licensed under [MIT](LICENSE). Baba Is You, its executable, scripts, levels,
artwork, and trademarks belong to their respective owners and are **not** included or
relicensed by this repository. This is an unofficial project, not affiliated with the game's
creators or Steam.
