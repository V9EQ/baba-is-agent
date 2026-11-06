import json

from conftest import make_state
from test_service import FakeBridge

from baba_is_agent.feedback import action_result
from baba_is_agent.presentation import Presenter, text_result
from baba_is_agent.service import GameService, parse_actions


def decode(result):
    assert result.structuredContent is None
    assert len(result.content) == 1
    return json.loads(result.content[0].text)


def unit(identifier=1, **changes):
    return dict(
        id=identifier, name="baba", x=2, y=3, dir=0, type="object", properties=["you"], **changes
    )


def test_reply_is_one_minified_copy():
    result = text_result({"value": [1, 2, 3]})
    content = result.content[0]
    assert content.type == "text"
    assert content.text == '{"value":[1,2,3]}'
    assert result.structuredContent is None


def test_delta_uses_same_group_and_coordinate_format_as_board():
    before = make_state(units=[unit()])
    after = make_state(units=[dict(unit(), x=3)])
    presenter = Presenter()
    board = decode(presenter.render(before))
    result = decode(presenter.render(after, action=action_result(before, after, 1, 1)))
    assert board["kind"] == "board"
    assert result["kind"] == "delta"
    assert result["changed"] == [{"name": "baba", "properties": ["you"], "at": [[3, 3, 0, 1]]}]
    assert result["controlled"][0]["x"] == 3
    assert result["executed"] == 1
    assert not {"objects", "rules", "frame", "grid"}.intersection(result)


def test_first_reply_scene_change_resize_and_resume_include_full_board():
    presenter = Presenter()
    state = make_state()
    for changes in [{}, {"level": "1level"}, {"width": 20}, {"height": 30}]:
        state = state.model_copy(update=changes)
        result = decode(presenter.render(state))
        assert result["kind"] == "board" and "objects" in result
        assert "refresh" not in result  # No extra tool call required to establish a baseline.
    presenter.render(state.model_copy(update={"menu": "pause"}))
    assert decode(presenter.render(state))["kind"] == "board"


def test_board_keeps_inert_objects_stacks_directions_and_conditions():
    units = [
        dict(unit(), name="rock", properties=[]),
        dict(unit(), id=2, name="text_rock", properties=["push"]),
    ]
    state = make_state(
        units=units, rules=[{"words": ["rock", "is", "push"], "conditions": [["on", ["grass"]]]}]
    )
    board = decode(Presenter().render(state, full=True))
    assert board["objects"] == [
        {"name": "rock", "properties": [], "at": [[2, 3, 0, 1]]},
        {"name": "text_rock", "properties": ["push"], "at": [[2, 3, 0, 2]]},
    ]
    assert board["rules"][0]["conditions"] == [["on", ["grass"]]]
    assert "grid" not in board
    legend = board["legend"]
    assert legend["at"] == ["x", "y", "direction", "id"]
    assert legend["directions"]["idle"] == 4


def test_delta_transformation_deletion_and_new_unit():
    before = make_state(
        units=[dict(unit(), name="box", properties=["push", "weak"]), dict(unit(), id=2)]
    )
    after = make_state(units=[dict(unit(), name="key", properties=["open"]), dict(unit(), id=3)])
    presenter = Presenter()
    presenter.render(before)
    result = decode(presenter.render(after))
    assert result["removed"] == [2]
    assert result["effects"] == [
        {"id": 1, "was": "box", "now": "key", "gained": ["open"], "lost": ["push", "weak"]}
    ]
    assert result["changed"][0]["properties"] == ["open"]  # Never assume PUSH from the name key.
    assert result["changed"][1]["at"][0][3] == 3
    assert "effects" not in decode(presenter.render(after))


def test_delta_rules_buttons_and_explicit_resynchronization():
    presenter = Presenter()
    presenter.render(make_state())
    state = make_state(
        rules=[{"words": ["baba", "is", "you"], "conditions": []}],
        buttons=[{"name": "resume", "text": "Resume", "disabled": 0, "x": 0, "y": 0}],
    )
    delta = decode(presenter.render(state))
    assert "rules" in delta and "buttons" in delta
    full = decode(presenter.render(state, full=True))
    assert full["kind"] == "board" and "objects" in full


def test_large_static_board_is_not_repeated_after_a_single_move():
    objects = [
        dict(unit(), id=i + 2, x=i % 30, y=i // 30, name="grass", properties=[])
        for i in range(230)
    ]
    before = make_state(width=35, height=20, units=[*objects, unit()])
    after = before.model_copy(
        update={"units": [*before.units[:-1], before.units[-1].model_copy(update={"x": 3})]}
    )
    presenter = Presenter()
    board = presenter.render(before)
    delta = presenter.render(after, action=action_result(before, after, 1, 1))
    board_text, delta_text = board.content[0], delta.content[0]
    assert board_text.type == "text"
    assert delta_text.type == "text"
    assert len(board_text.text) < 6000
    assert len(delta_text.text) < 1000
    assert sum(len(g["at"]) for g in decode(board)["objects"]) == 231
    assert sum(len(g["at"]) for g in decode(delta)["changed"]) == 1


def test_compact_actions_are_expanded_once():
    assert parse_actions("R3 U2,Z") == ["right"] * 3 + ["up"] * 2 + ["undo"]


def test_engine_batch_has_one_ack_for_all_moves(settings):
    bridge = FakeBridge(make_state(capabilities=["batch"]), make_state(executed=8))
    result = GameService(settings, bridge=bridge).act("R8")
    assert result.executed == 8
    assert bridge.request.call_count == 2
    bridge.request.assert_called_with("batch", actions=["right"] * 8)
