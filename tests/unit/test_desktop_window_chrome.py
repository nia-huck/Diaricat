from __future__ import annotations

import ctypes
from types import SimpleNamespace

import pytest

import diaricat.desktop as desktop


class _FakeDwmApi:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int, int]] = []

    def DwmSetWindowAttribute(self, hwnd: int, attr: int, value_ptr: ctypes.c_void_p, size: int) -> int:
        if attr in {20, 33}:
            value = ctypes.cast(value_ptr, ctypes.POINTER(ctypes.c_int)).contents.value
        else:
            value = ctypes.cast(value_ptr, ctypes.POINTER(ctypes.c_uint)).contents.value
        self.calls.append((hwnd, attr, value, size))
        return 0


class _FakeUser32:
    def __init__(self) -> None:
        self.style = 0
        self.ex_style = 0x00020200
        self.set_style_calls = 0
        self.set_ex_style_calls = 0
        self.set_window_pos_calls = 0

    def GetWindowLongW(self, _hwnd: int, index: int) -> int:
        if index == -16:
            return self.style
        if index == -20:
            return self.ex_style
        return 0

    def SetWindowLongW(self, _hwnd: int, index: int, value: int) -> int:
        if index == -16:
            self.style = value
            self.set_style_calls += 1
        elif index == -20:
            self.ex_style = value
            self.set_ex_style_calls += 1
        return value

    def SetWindowPos(
        self, _hwnd: int, _insert_after: int, _x: int, _y: int, _cx: int, _cy: int, _flags: int
    ) -> int:
        self.set_window_pos_calls += 1
        return 1


def _make_api(monkeypatch: pytest.MonkeyPatch) -> desktop.WindowAPI:
    monkeypatch.setattr(desktop.os, "name", "nt", raising=False)
    api = desktop.WindowAPI()
    api._window = object()
    monkeypatch.setattr(api, "_get_hwnd", lambda: 101)
    return api


def test_apply_dark_window_chrome_uses_black_border_and_keeps_default_corners(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _make_api(monkeypatch)
    fake_dwm = _FakeDwmApi()
    monkeypatch.setattr(desktop.ctypes, "windll", SimpleNamespace(dwmapi=fake_dwm), raising=False)

    api._apply_dark_window_chrome(state_hint="normal")

    attrs = {attr: value for _hwnd, attr, value, _size in fake_dwm.calls}
    assert attrs[20] == 1
    assert attrs[33] == 0
    assert attrs[34] == 0x00000000


def test_apply_dark_window_chrome_uses_square_corners_when_maximized(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _make_api(monkeypatch)
    fake_dwm = _FakeDwmApi()
    monkeypatch.setattr(desktop.ctypes, "windll", SimpleNamespace(dwmapi=fake_dwm), raising=False)

    api._apply_dark_window_chrome(state_hint="maximized")

    attrs = {attr: value for _hwnd, attr, value, _size in fake_dwm.calls}
    assert attrs[33] == 1


def test_ensure_native_resize_and_snap_styles_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _make_api(monkeypatch)
    fake_user32 = _FakeUser32()
    monkeypatch.setattr(desktop.ctypes, "windll", SimpleNamespace(user32=fake_user32), raising=False)

    api._ensure_native_resize_and_snap_styles()
    api._ensure_native_resize_and_snap_styles()

    assert fake_user32.set_style_calls == 1
    assert fake_user32.set_ex_style_calls == 1
    assert fake_user32.set_window_pos_calls == 2


def test_webview2_preflight_raises_when_runtime_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop.os, "name", "nt", raising=False)
    monkeypatch.setattr(desktop, "_has_webview2_runtime", lambda: False)

    with pytest.raises(RuntimeError, match="WebView2"):
        desktop._ensure_webview2_runtime_available()


def test_webview2_preflight_passes_when_runtime_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop.os, "name", "nt", raising=False)
    monkeypatch.setattr(desktop, "_has_webview2_runtime", lambda: True)

    desktop._ensure_webview2_runtime_available()


def test_splash_html_contains_spark_effects_and_motion_fallback() -> None:
    html = desktop._make_splash_html("data:image/png;base64,Zm9v")

    assert 'class="spark-field"' in html
    assert "@media (prefers-reduced-motion: reduce)" in html
    assert "Transcripcion inteligente y privada" in html
    assert 'class="logo"' in html
