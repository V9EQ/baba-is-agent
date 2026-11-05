"""Linux menu keyboard and XWayland window activation. No capture or OCR."""

from __future__ import annotations

import ctypes as ct
import ctypes.util
import time
from collections.abc import Callable
from types import TracebackType
from typing import Protocol

from baba_is_agent.errors import InputUnavailableError
from baba_is_agent.models import Key


class Keyboard(Protocol):
    def press(self, key: Key) -> None: ...

    def close(self) -> None: ...


class _ClientData(ct.Union):
    _fields_ = [("longs", ct.c_long * 5)]


class _ClientMessage(ct.Structure):
    _fields_ = [
        ("type", ct.c_int),
        ("serial", ct.c_ulong),
        ("send_event", ct.c_int),
        ("display", ct.c_void_p),
        ("window", ct.c_ulong),
        ("message_type", ct.c_ulong),
        ("format", ct.c_int),
        ("data", _ClientData),
    ]


class _XEvent(ct.Union):
    _fields_ = [("client", _ClientMessage), ("padding", ct.c_long * 24)]


class XWaylandWindow:
    """Find the innermost game client rather than Mutter's decoration window."""

    def __init__(self) -> None:
        library = ctypes.util.find_library("X11")
        if library is None:
            raise InputUnavailableError("libX11 is required for menu window activation")
        self._x11 = ct.CDLL(library)
        self._configure_abi()
        self._display = self._x11.XOpenDisplay(None)
        if not self._display:
            raise InputUnavailableError(
                "Cannot open DISPLAY. Pass DISPLAY and XAUTHORITY to the MCP server."
            )

    def _configure_abi(self) -> None:
        x11 = self._x11
        x11.XOpenDisplay.argtypes = [ct.c_char_p]
        x11.XOpenDisplay.restype = ct.c_void_p
        x11.XDefaultRootWindow.argtypes = [ct.c_void_p]
        x11.XDefaultRootWindow.restype = ct.c_ulong
        x11.XQueryTree.argtypes = [
            ct.c_void_p,
            ct.c_ulong,
            ct.POINTER(ct.c_ulong),
            ct.POINTER(ct.c_ulong),
            ct.POINTER(ct.POINTER(ct.c_ulong)),
            ct.POINTER(ct.c_uint),
        ]
        x11.XFetchName.argtypes = [ct.c_void_p, ct.c_ulong, ct.POINTER(ct.c_char_p)]
        x11.XFree.argtypes = [ct.c_void_p]
        x11.XSetInputFocus.argtypes = [ct.c_void_p, ct.c_ulong, ct.c_int, ct.c_ulong]
        x11.XRaiseWindow.argtypes = [ct.c_void_p, ct.c_ulong]
        x11.XFlush.argtypes = [ct.c_void_p]
        x11.XCloseDisplay.argtypes = [ct.c_void_p]
        x11.XInternAtom.argtypes = [ct.c_void_p, ct.c_char_p, ct.c_int]
        x11.XInternAtom.restype = ct.c_ulong
        x11.XSendEvent.argtypes = [
            ct.c_void_p,
            ct.c_ulong,
            ct.c_int,
            ct.c_long,
            ct.POINTER(_XEvent),
        ]

    def _find(self, window: int, depth: int = 0) -> int | None:
        title = ct.c_char_p()
        matches = False
        if self._x11.XFetchName(self._display, window, ct.byref(title)):
            try:
                matches = bool(
                    title.value
                    and title.value.decode(errors="replace").casefold() == "baba is you"
                )
            finally:
                if title:
                    self._x11.XFree(title)
        if depth >= 6:
            return window if matches else None
        root, parent, count = ct.c_ulong(), ct.c_ulong(), ct.c_uint()
        children = ct.POINTER(ct.c_ulong)()
        found = self._x11.XQueryTree(
            self._display,
            window,
            ct.byref(root),
            ct.byref(parent),
            ct.byref(children),
            ct.byref(count),
        )
        identifiers = []
        try:
            if found:
                identifiers = [children[index] for index in range(count.value)]
        finally:
            if children:
                self._x11.XFree(children)
        for child in identifiers:
            if (client := self._find(child, depth + 1)) is not None:
                return client
        return window if matches else None

    def focus(self) -> None:
        """Ask the compositor to activate the game; never focus another named app."""
        root = self._x11.XDefaultRootWindow(self._display)
        window = self._find(root)
        if window is None:
            raise InputUnavailableError(
                "Baba Is You XWayland window not found. Launch the game first."
            )
        event = _XEvent()
        event.client.type = 33  # ClientMessage
        event.client.display = self._display
        event.client.window = window
        event.client.message_type = self._x11.XInternAtom(self._display, b"_NET_ACTIVE_WINDOW", 0)
        event.client.format = 32
        event.client.data.longs[0] = 2  # EWMH source: pager / external controller.
        self._x11.XSendEvent(self._display, root, 0, (1 << 20) | (1 << 19), ct.byref(event))
        self._x11.XRaiseWindow(self._display, window)
        self._x11.XSetInputFocus(self._display, window, 1, 0)
        self._x11.XFlush(self._display)
        time.sleep(0.12)

    def __enter__(self) -> XWaylandWindow:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._x11.XCloseDisplay(self._display)


def focus_game() -> None:
    with XWaylandWindow() as window:
        window.focus()


class LinuxKeyboard:
    """Lazily allocate a virtual keyboard; exact gameplay uses the Lua bridge instead."""

    def __init__(self, focus: Callable[[], None] = focus_game) -> None:
        self._focus = focus
        self._device = None

    def press(self, key: Key) -> None:
        # Keep evdev optional at import time: offline tests and metadata need no device.
        try:
            from evdev import UInput, ecodes
        except ImportError as error:
            raise InputUnavailableError("Menu input requires Linux and evdev") from error
        codes = {
            "up": ecodes.KEY_UP,
            "down": ecodes.KEY_DOWN,
            "left": ecodes.KEY_LEFT,
            "right": ecodes.KEY_RIGHT,
            "confirm": ecodes.KEY_ENTER,
            "escape": ecodes.KEY_ESC,
            "space": ecodes.KEY_SPACE,
            "wait": ecodes.KEY_SPACE,
            "undo": ecodes.KEY_Z,
            "restart": ecodes.KEY_R,
        }
        if key not in codes:
            raise ValueError(f"Unsupported key: {key}")
        if self._device is None:
            try:
                self._device = UInput(
                    {ecodes.EV_KEY: sorted(set(codes.values()))}, name="Baba MCP keyboard"
                )
            except OSError as error:
                raise InputUnavailableError(
                    "Cannot create /dev/uinput keyboard. Grant a user ACL as documented; "
                    "do not run the MCP server as root."
                ) from error
            time.sleep(1.0)  # Allow the compositor to discover the device.
        self._focus()
        code = codes[key]
        self._device.write(ecodes.EV_KEY, code, 1)
        self._device.syn()
        try:
            time.sleep(0.07)
        finally:
            self._device.write(ecodes.EV_KEY, code, 0)
            self._device.syn()
        time.sleep(0.22)

    def close(self) -> None:
        if self._device is not None:
            self._device.close()
            self._device = None
