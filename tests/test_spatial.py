from conftest import make_state
from test_feedback import PLAYER
from test_presentation import decode

from baba_is_agent.presentation import Presenter, spatial_board


def test_spatial_grid_keeps_stacks_inert_objects_and_word_tiles():
    state = make_state(
        width=4,
        height=2,
        units=[
            dict(PLAYER, x=1, y=0),
            dict(PLAYER, id=2, name="key", properties=["open"], x=1, y=0),
            dict(PLAYER, id=3, name="text_key", properties=["push"], x=2, y=0),
            dict(PLAYER, id=4, name="grass", properties=[], x=0, y=1),
        ],
        rules=[{"words": ["key", "is", "open"], "conditions": [["on", ["grass"]]]}],
    )
    board = decode(Presenter(spatial=True).render(state, "board"))
    assert board["columns"] == [0, 1, 2, 3]
    assert board["grid"] == ["00 | . baba+key KEY .", "01 | grass . . ."]
    assert board["objects"][1]["positions"] == [{"x": 1, "y": 0, "direction": 0, "id": 2}]
    assert "at" not in board["objects"][1]
    assert board["objects"][3]["properties"] == []
    assert board["rules"][0]["conditions"] == [["on", ["grass"]]]


def test_spatial_changes_describe_facts_not_assumed_pushability():
    before = make_state(units=[dict(PLAYER, name="box", properties=["push", "weak"])])
    after = make_state(units=[dict(PLAYER, name="key", properties=["open"])])
    presenter = Presenter(spatial=True)
    presenter.render(before, "board")
    result = decode(presenter.render(after, "board"))
    assert result["changes_since_previous_reply"] == [
        {
            "id": 1,
            "before": {"name": "box", "properties": ["push", "weak"]},
            "after": {"name": "key", "properties": ["open"]},
        }
    ]
    assert "changes_since_previous_reply" not in decode(presenter.render(after, "board"))
    assert "changes_since_previous_reply" not in decode(
        presenter.render(after.model_copy(update={"level": "another"}), "board")
    )


def test_spatial_missing_dimensions_is_valid_empty_grid():
    assert spatial_board(make_state())["grid"] == []
