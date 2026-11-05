"""Agent-facing control status and action outcomes, independent of delta baselines."""

from baba_is_agent.models import ActionResult, GameState, JsonObject


def control_context(state: GameState) -> JsonObject:
    """Report ordinary controllers without claiming every YOU mechanic is a unit."""
    players = [u for u in state.units if {"you", "you2"}.intersection(u.properties)]
    cursors = [u for u in state.units if "select" in u.properties]
    special = any(
        len(rule.words) >= 3
        and rule.words[0] in {"empty", "level"}
        and rule.words[1] == "is"
        and rule.words[2] in {"you", "you2"}
        for rule in state.rules
    )
    if players:
        controller = "you" if any("you" in u.properties for u in players) else "you2"
    elif cursors:
        controller = "cursor"
    else:
        controller = "special" if special else "none"
    controlled = players + [u for u in cursors if u not in players]
    if state.menu == "levelintro":
        phase = "intro"
    elif state.menu != "ingame" or state.paused:
        phase = "menu"
    elif cursors:
        phase = "map"
    else:
        phase = "auto" if state.auto else "puzzle"
    data: JsonObject = {
        "phase": phase,
        "ready": state.ready,
        "paused": state.paused,
        "ignore": state.ignore,
        "no_player": state.no_player,
        "controller": controller,
        "controlled": [
            {"id": u.id, "name": u.name, "x": u.x, "y": u.y, "direction": u.dir}
            for u in controlled
        ],
        "can_undo": state.undo_depth > 0,
    }
    if state.won:
        data["recovery_hint"] = "Victory reported; read get_board if the scene changed."
    elif phase == "intro":
        data["recovery_hint"] = "press(key='confirm') dismisses the introduction."
    elif phase == "menu":
        data["recovery_hint"] = "Use reported menu buttons with choose_menu, or press."
    elif phase == "map":
        data["recovery_hint"] = "Move the cursor with act, then press(key='confirm')."
    elif phase == "auto":
        data["recovery_hint"] = "AUTO requires realtime input with press."
    elif controller == "none" and state.no_player:
        data["recovery_hint"] = "No ordinary control: try act(actions='Z') or restart_level."
    return data


def ordinary_control_lost(state: GameState) -> bool:
    """Conservatively exempt maps, special YOU rules, AUTO, and unready scenes."""
    context = control_context(state)
    return (
        state.ready
        and bool(state.no_player)
        and context["phase"] == "puzzle"
        and context["controller"] == "none"
    )


def action_result(
    initial: GameState, current: GameState, requested: int, executed: int
) -> ActionResult:
    """Describe what happened, not how much of a plan was useful or successful."""
    context = control_context(current)
    if current.won or current.wins != initial.wins:
        reason = "win"
    elif current.level_key != initial.level_key:
        reason = "transition"
    elif not current.ready:
        reason = "not_ready"
    elif ordinary_control_lost(current):
        reason = "control_lost"
    elif current.no_player and any(
        {"you", "you2"}.intersection(u.properties) for u in initial.units
    ):
        reason = "control_lost" if context["controller"] == "none" else "control_changed"
    else:
        reason = "completed" if executed == requested else "interrupted"
    # Ignore transport counters and ordering; compare only the visible board/rules/scene.
    changed = (
        initial.level_key != current.level_key
        or {u.id: u for u in initial.units} != {u.id: u for u in current.units}
        or initial.rules != current.rules
        or getattr(initial, "width", 0) != getattr(current, "width", 0)
        or getattr(initial, "height", 0) != getattr(current, "height", 0)
    )
    return ActionResult(
        state=current,
        requested=requested,
        executed=executed,
        stop_reason=reason,
        board_changed=changed,
    )
