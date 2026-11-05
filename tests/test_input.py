from typing import cast
from unittest.mock import Mock, call

import pytest

from baba_is_agent.errors import InputUnavailableError
from baba_is_agent.input import LinuxKeyboard
from baba_is_agent.models import Key


def test_key_is_released_when_hold_is_interrupted(monkeypatch):
    from evdev import ecodes

    keyboard = LinuxKeyboard(focus=Mock())
    device = Mock()
    keyboard._device = device
    monkeypatch.setattr("baba_is_agent.input.time.sleep", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        keyboard.press("confirm")
    assert device.write.call_args_list == [
        call(ecodes.EV_KEY, ecodes.KEY_ENTER, 1),
        call(ecodes.EV_KEY, ecodes.KEY_ENTER, 0),
    ]
    keyboard.close()
    device.close.assert_called_once()
    keyboard.close()
    device.close.assert_called_once()


def test_uinput_error_is_actionable(monkeypatch):
    monkeypatch.setattr("evdev.UInput", Mock(side_effect=PermissionError))
    with pytest.raises(InputUnavailableError, match="do not run.*root"):
        LinuxKeyboard(focus=Mock()).press("confirm")


def test_unknown_key_never_reaches_desktop():
    focus = Mock()
    with pytest.raises(ValueError):
        LinuxKeyboard(focus=focus).press(cast(Key, "delete"))
    focus.assert_not_called()
