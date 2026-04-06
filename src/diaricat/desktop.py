"""Desktop launcher using pywebview with in-process uvicorn."""

from __future__ import annotations

import base64
import ctypes
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn

from diaricat.settings import load_settings
from diaricat.utils.logging import SESSION_ID
from diaricat.utils.paths import ensure_runtime_dirs

logger = logging.getLogger(__name__)


def _show_windows_error_dialog(title: str, message: str) -> None:
    """Show a fatal startup error dialog in desktop mode (Windows only)."""
    if os.name != "nt":
        return
    try:
        MB_ICONERROR = 0x00000010
        MB_OK = 0x00000000
        ctypes.windll.user32.MessageBoxW(0, message, title, MB_OK | MB_ICONERROR)
    except Exception:
        # If GUI dialog fails, fallback is the log entry from caller.
        return


def _has_webview2_runtime() -> bool:
    """Detect whether Edge WebView2 runtime is available for pywebview on Windows."""
    if os.name != "nt":
        return True

    try:
        import webview.platforms.winforms as winforms
    except Exception:
        return False

    detected = bool(getattr(winforms, "is_chromium", False))
    if detected:
        return True

    detector = getattr(winforms, "_is_chromium", None)
    if callable(detector):
        try:
            return bool(detector())
        except Exception:
            return False

    return False


def _ensure_webview2_runtime_available() -> None:
    """Abort desktop startup with a clear message if WebView2 is missing."""
    if _has_webview2_runtime():
        return

    raise RuntimeError(
        "Microsoft Edge WebView2 Runtime no esta instalado o no esta disponible. "
        "Instalalo desde https://go.microsoft.com/fwlink/p/?LinkId=2124703 y vuelve a abrir Diaricat."
    )


class WindowAPI:
    """Exposes window control methods to the frontend via window.pywebview.api.*"""

    def __init__(self) -> None:
        self._window = None
        self._is_fullscreen = False

    def set_window(self, window: object) -> None:
        self._window = window
        self._refresh_window_chrome()

    def _refresh_window_chrome(self, state_hint: str | None = None) -> None:
        self._ensure_native_resize_and_snap_styles()
        self._apply_dark_window_chrome(state_hint=state_hint)
        self._ensure_maximized_bounds_work_area()

    def _ensure_native_resize_and_snap_styles(self) -> None:
        if os.name != "nt":
            return
        hwnd = self._get_hwnd()
        if not hwnd:
            return

        GWL_STYLE = -16
        GWL_EXSTYLE = -20
        WS_THICKFRAME = 0x00040000
        WS_MAXIMIZEBOX = 0x00010000
        WS_EX_APPWINDOW = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020

        try:
            user32 = ctypes.windll.user32
            style = int(user32.GetWindowLongW(hwnd, GWL_STYLE))
            desired_style = style | WS_THICKFRAME | WS_MAXIMIZEBOX
            if desired_style != style:
                user32.SetWindowLongW(hwnd, GWL_STYLE, desired_style)

            ex_style = int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
            desired_ex_style = (ex_style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
            if desired_ex_style != ex_style:
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, desired_ex_style)

            user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
            )
        except Exception:
            return

    def _apply_dark_window_chrome(self, state_hint: str | None = None) -> None:
        """Apply DWM chrome attributes (dark mode, border, corner preference)."""
        if os.name != "nt":
            return

        hwnd = self._get_hwnd()
        if not hwnd:
            return

        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWA_BORDER_COLOR = 34
        DWMWA_CAPTION_COLOR = 35
        DWMWA_TEXT_COLOR = 36
        DWMWCP_DEFAULT = 0
        DWMWCP_DONOTROUND = 1
        COLOR_BLACK = ctypes.c_uint(0x00000000)
        COLOR_WHITE = ctypes.c_uint(0x00FFFFFF)
        DARK_ON = ctypes.c_int(1)
        state = (state_hint or self.get_window_state().get("state", "normal")).lower()
        corner_pref = ctypes.c_int(DWMWCP_DONOTROUND if state in {"maximized", "fullscreen"} else DWMWCP_DEFAULT)

        # Allow dark mode for this HWND (undocumented ord 133, then documented)
        try:
            ctypes.windll.uxtheme[133](hwnd, True)
        except Exception:
            pass
        try:
            ctypes.windll.uxtheme.AllowDarkModeForWindow(hwnd, True)
        except Exception:
            pass
        # Force the non-client frame to repaint with dark theme
        try:
            ctypes.windll.uxtheme.SetWindowTheme(hwnd, "DarkMode_Explorer", None)
        except Exception:
            pass

        try:
            dwmapi = ctypes.windll.dwmapi
            dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(DARK_ON),
                ctypes.sizeof(DARK_ON),
            )
            dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(corner_pref),
                ctypes.sizeof(corner_pref),
            )
            dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_BORDER_COLOR,
                ctypes.byref(COLOR_BLACK),
                ctypes.sizeof(COLOR_BLACK),
            )
            dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_CAPTION_COLOR,
                ctypes.byref(COLOR_BLACK),
                ctypes.sizeof(COLOR_BLACK),
            )
            dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_TEXT_COLOR,
                ctypes.byref(COLOR_WHITE),
                ctypes.sizeof(COLOR_WHITE),
            )
            # Force non-client area repaint so dark mode takes effect immediately
            WM_NCACTIVATE = 0x0086
            ctypes.windll.user32.SendMessageW(hwnd, WM_NCACTIVATE, False, 0)
            ctypes.windll.user32.SendMessageW(hwnd, WM_NCACTIVATE, True, 0)
        except Exception:
            return

    def _ensure_maximized_bounds_work_area(self) -> None:
        """Keep borderless maximize constrained to Windows work area (taskbar visible)."""
        if os.name != "nt" or self._window is None:
            return

        native = getattr(self._window, "native", None)
        if native is None:
            return

        try:
            import System.Windows.Forms as WinForms  # type: ignore

            screen = WinForms.Screen.FromHandle(native.Handle)
            work_area = screen.WorkingArea
            try:
                native.MaximizedBounds = work_area
            except Exception:
                import System.Drawing as Drawing  # type: ignore

                native.MaximizedBounds = Drawing.Rectangle(
                    int(work_area.Left),
                    int(work_area.Top),
                    int(work_area.Width),
                    int(work_area.Height),
                )
        except Exception:
            return

    def _get_hwnd(self) -> int | None:
        if self._window is None:
            return None
        native = getattr(self._window, "native", None)
        if native is None:
            return None
        handle = getattr(native, "Handle", None)
        if handle is None:
            return None

        try:
            return int(handle.ToInt64())
        except Exception:
            pass
        try:
            return int(handle.ToInt32())
        except Exception:
            pass
        try:
            return int(handle)
        except Exception:
            pass

        if os.name == "nt":
            try:
                title = str(getattr(self._window, "title", "") or "")
                if title:
                    hwnd = int(ctypes.windll.user32.FindWindowW(None, title))
                    if hwnd:
                        return hwnd
            except Exception:
                pass
        return None

    def get_window_state(self) -> dict[str, str]:
        if self._window is None:
            return {"state": "unknown"}

        if self._is_fullscreen:
            return {"state": "fullscreen"}

        hwnd = self._get_hwnd()
        if hwnd and os.name == "nt":
            try:
                if ctypes.windll.user32.IsIconic(hwnd):
                    return {"state": "minimized"}
                if ctypes.windll.user32.IsZoomed(hwnd):
                    return {"state": "maximized"}
            except Exception:
                pass

        native = getattr(self._window, "native", None)
        window_state = getattr(native, "WindowState", None) if native is not None else None
        if window_state is not None:
            state_text = str(window_state).lower()
            if "maximized" in state_text:
                return {"state": "maximized"}
            if "minimized" in state_text:
                return {"state": "minimized"}

        return {"state": "normal"}

    def minimize(self) -> None:
        if self._window is not None:
            self._window.minimize()

    def toggle_maximize(self) -> None:
        if self._window is None:
            return
        state = self.get_window_state().get("state")
        if state == "fullscreen":
            self._window.toggle_fullscreen()
            self._is_fullscreen = False
            self._refresh_window_chrome(state_hint="normal")
            return
        if state == "maximized":
            self._window.restore()
            self._refresh_window_chrome(state_hint="normal")
            return
        self._refresh_window_chrome(state_hint="normal")
        self._window.maximize()
        self._apply_dark_window_chrome(state_hint="maximized")

    def toggle_fullscreen(self) -> None:
        if self._window is not None:
            entering_fullscreen = not self._is_fullscreen
            self._window.toggle_fullscreen()
            self._is_fullscreen = entering_fullscreen
            self._refresh_window_chrome(state_hint="fullscreen" if entering_fullscreen else "normal")

    def start_window_drag(self) -> bool:
        if os.name != "nt":
            return False
        state = self.get_window_state().get("state")
        if state == "fullscreen":
            return False

        self._refresh_window_chrome(state_hint="maximized" if state == "maximized" else "normal")
        hwnd = self._get_hwnd()
        if not hwnd:
            return False

        WM_NCLBUTTONDOWN = 0x00A1
        HTCAPTION = 0x0002
        SW_RESTORE = 9
        try:
            # If window is maximized, restore first to preserve natural drag behavior.
            if ctypes.windll.user32.IsZoomed(hwnd):
                ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
                self._apply_dark_window_chrome(state_hint="normal")
            ctypes.windll.user32.ReleaseCapture()
            ctypes.windll.user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)
            return True
        except Exception:
            return False

    def start_window_resize(self, edge: str) -> bool:
        if os.name != "nt":
            return False
        if self.get_window_state().get("state") in {"fullscreen", "maximized"}:
            return False

        self._refresh_window_chrome(state_hint="normal")
        hwnd = self._get_hwnd()
        if not hwnd:
            return False

        edge_map = {
            "left": 0x000A,
            "right": 0x000B,
            "top": 0x000C,
            "topright": 0x000E,
            "bottom": 0x000F,
            "bottomright": 0x0011,
            "bottomleft": 0x0010,
            "topleft": 0x000D,
        }
        hit = edge_map.get((edge or "").strip().lower())
        if hit is None:
            return False

        WM_NCLBUTTONDOWN = 0x00A1
        try:
            ctypes.windll.user32.ReleaseCapture()
            ctypes.windll.user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, hit, 0)
            return True
        except Exception:
            return False

    def close_window(self) -> None:
        if self._window is not None:
            self._window.destroy()


def _healthcheck(url: str, timeout: float = 0.5) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (URLError, OSError):
        return False


def _is_bindable(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _find_available_port(host: str, start_port: int, attempts: int = 50) -> int:
    for offset in range(attempts):
        candidate = start_port + offset
        if _is_bindable(host, candidate):
            return candidate
    raise RuntimeError("No free local port available for desktop runtime.")


def _resolve_icon_path() -> Path | None:
    project_root = Path(__file__).resolve().parents[2]
    bundled_root = Path(getattr(sys, "_MEIPASS", project_root))

    candidates = [
        bundled_root / "assets" / "diarcat.ico",
        project_root / "assets" / "diarcat.ico",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _resolve_logo_data_uri() -> str | None:
    """Return a base64 PNG data URI for the app logo, or None if not found."""
    project_root = Path(__file__).resolve().parents[2]
    bundled_root = Path(getattr(sys, "_MEIPASS", project_root))
    candidates = [
        bundled_root / "assets" / "diaricat-logo.png",
        project_root / "assets" / "diaricat-logo.png",
        project_root / "frontend" / "src" / "assets" / "diaricat-logo.png",
    ]
    for p in candidates:
        if p.exists():
            return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
    return None


def _make_splash_html(logo_uri: str | None) -> str:
    """Generate standalone splash HTML with embedded logo."""
    logo_html = (
        f'<img src="{logo_uri}" alt="Diaricat" class="logo" draggable="false" />'
        if logo_uri
        else '<div class="logo-fallback">D</div>'
    )
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8" />
<meta name="color-scheme" content="dark" />
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{
    width: 100%;
    height: 100%;
    overflow: hidden;
    user-select: none;
    -webkit-app-region: drag;
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
    background:
      radial-gradient(ellipse 85% 60% at 50% -20%, rgba(128, 88, 245, 0.32) 0%, rgba(8, 7, 16, 0) 66%),
      radial-gradient(ellipse 55% 46% at 88% 88%, rgba(72, 186, 255, 0.14) 0%, rgba(6, 6, 12, 0) 72%),
      #06060d;
    color: rgba(230, 222, 248, 0.92);
  }}
  .splash-root {{
    position: relative;
    width: 100%;
    height: 100%;
    display: grid;
    place-items: center;
    isolation: isolate;
  }}
  .spark-field {{
    position: absolute;
    inset: -12%;
    pointer-events: none;
    z-index: 0;
    opacity: 0.92;
  }}
  .spark-field::before,
  .spark-field::after {{
    content: '';
    position: absolute;
    inset: 0;
    background:
      radial-gradient(circle, rgba(196, 164, 255, 0.28) 0.8px, transparent 1.2px),
      radial-gradient(circle, rgba(146, 224, 255, 0.2) 0.8px, transparent 1.2px),
      radial-gradient(circle, rgba(255, 255, 255, 0.22) 1px, transparent 1.4px);
    background-size: 120px 120px, 160px 160px, 220px 220px;
    mix-blend-mode: screen;
  }}
  .spark-field::before {{
    animation: sparkDriftA 12s linear infinite;
  }}
  .spark-field::after {{
    opacity: 0.58;
    transform: scale(1.08);
    animation: sparkDriftB 17s linear infinite;
  }}
  .ambient {{
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 0;
    background:
      radial-gradient(ellipse 70% 35% at 50% 18%, rgba(180, 145, 255, 0.2) 0%, transparent 76%),
      radial-gradient(ellipse 45% 30% at 25% 80%, rgba(112, 196, 255, 0.1) 0%, transparent 76%);
  }}
  .panel {{
    position: relative;
    z-index: 1;
    min-width: 320px;
    padding: 24px 26px 22px;
    border-radius: 20px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 14px;
    background:
      radial-gradient(ellipse 80% 54% at 50% 28%, rgba(160, 130, 255, 0.07) 0%, rgba(255, 255, 255, 0.02) 35%, transparent 65%),
      rgba(15, 10, 28, 0.36);
    backdrop-filter: blur(18px) saturate(1.4) brightness(1.08);
    -webkit-backdrop-filter: blur(18px) saturate(1.4) brightness(1.08);
    box-shadow:
      0 2px 4px rgba(0, 0, 0, 0.4),
      0 10px 34px -4px rgba(0, 0, 0, 0.46),
      0 0 72px -20px rgba(128, 88, 245, 0.34),
      inset 0 1px 0 rgba(220, 198, 255, 0.2),
      inset 0 -1px 8px rgba(0, 0, 0, 0.16);
    animation: panelEnter 0.32s ease-out both;
  }}
  .panel::before {{
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    padding: 1.4px;
    background: linear-gradient(
      170deg,
      rgba(200, 166, 255, 0.56) 0%,
      rgba(145, 106, 231, 0.24) 28%,
      rgba(96, 72, 196, 0.07) 64%,
      rgba(70, 48, 160, 0.02) 100%
    );
    pointer-events: none;
    -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    -webkit-mask-composite: destination-out;
    mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    mask-composite: exclude;
  }}
  .logo {{
    width: 76px;
    height: 76px;
    border-radius: 20px;
    object-fit: contain;
    animation: logoGlow 2.7s ease-in-out infinite;
  }}
  .logo-fallback {{
    width: 76px;
    height: 76px;
    border-radius: 20px;
    background: rgba(139, 92, 246, 0.12);
    border: 1px solid rgba(139, 92, 246, 0.25);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 34px;
    font-weight: 700;
    color: #8b5cf6;
    animation: logoGlow 2.7s ease-in-out infinite;
  }}
  .brand {{
    font-family: 'Space Grotesk', 'Segoe UI', sans-serif;
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.25px;
    color: rgba(232, 225, 248, 0.92);
  }}
  .tagline {{
    font-size: 11px;
    color: rgba(157, 145, 186, 0.62);
    letter-spacing: 0.02em;
    margin-top: -6px;
  }}
  .spinner-row {{
    margin-top: 3px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
  }}
  .spinner {{
    width: 18px;
    height: 18px;
    border: 2px solid rgba(139, 92, 246, 0.16);
    border-top-color: rgba(170, 130, 255, 0.84);
    border-radius: 50%;
    animation: spin 0.78s linear infinite;
  }}
  .status {{
    font-size: 10px;
    letter-spacing: 1.3px;
    text-transform: uppercase;
    color: rgba(182, 149, 255, 0.56);
    animation: pulse 1.9s ease-in-out infinite;
  }}
  @keyframes panelEnter {{
    from {{ opacity: 0; transform: translateY(8px) scale(0.985); }}
    to {{ opacity: 1; transform: translateY(0) scale(1); }}
  }}
  @keyframes logoGlow {{
    0%, 100% {{ filter: drop-shadow(0 0 16px rgba(139, 92, 246, 0.36)); }}
    50% {{ filter: drop-shadow(0 0 30px rgba(152, 112, 255, 0.72)); }}
  }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  @keyframes pulse {{
    0%, 100% {{ opacity: 0.42; }}
    50% {{ opacity: 1; }}
  }}
  @keyframes sparkDriftA {{
    0% {{ transform: translate3d(0, 0, 0) scale(1); }}
    100% {{ transform: translate3d(-80px, -36px, 0) scale(1.04); }}
  }}
  @keyframes sparkDriftB {{
    0% {{ transform: translate3d(0, 0, 0) scale(1.08); }}
    100% {{ transform: translate3d(100px, 54px, 0) scale(1.02); }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    .spark-field::before,
    .spark-field::after,
    .logo,
    .logo-fallback,
    .status,
    .spinner,
    .panel {{
      animation: none !important;
    }}
    .spark-field {{ opacity: 0.36; }}
  }}
</style>
</head>
<body>
<div class="splash-root">
  <div class="ambient"></div>
  <div class="spark-field" aria-hidden="true"></div>
  <div class="panel">
    {logo_html}
    <div class="brand">Diaricat</div>
    <div class="tagline">Transcripcion inteligente y privada</div>
    <div class="spinner-row">
      <div class="spinner"></div>
      <div class="status">Iniciando</div>
    </div>
  </div>
</div>
</body>
</html>"""


def _set_windows_app_id() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Diarcat.App")
    except Exception:
        pass


def _get_windows_work_area() -> tuple[int, int, int, int]:
    if os.name != "nt":
        return (0, 0, 1320, 860)

    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    rect = _RECT()
    SPI_GETWORKAREA = 0x0030
    ok = ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    if not ok:
        return (0, 0, 1320, 860)
    return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))


def _wait_for_server_and_navigate(host: str, port: int, window: object, timeout: float = 30.0) -> None:
    """Polls the backend in a background thread; navigates the window once ready."""
    url = f"http://{host}:{port}/v1/health"
    app_url = f"http://{host}:{port}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _healthcheck(url):
            try:
                window.load_url(app_url)  # type: ignore[attr-defined]
            except Exception as exc:
                logger.error("Failed to navigate window to app: %s", exc)
            return
        time.sleep(0.08)
    logger.error("Backend failed to start within %.0f seconds.", timeout)


def run_desktop_app() -> None:
    import webview

    from diaricat.api.app import create_app
    from diaricat.bootstrap import build_context, reset_context

    _set_windows_app_id()
    logger.info(
        "Desktop startup (session=%s, pid=%s, frozen=%s)",
        SESSION_ID,
        os.getpid(),
        getattr(sys, "frozen", False),
    )

    settings = load_settings()
    ensure_runtime_dirs(settings)
    try:
        _ensure_webview2_runtime_available()
    except RuntimeError as exc:
        message = str(exc)
        logger.error("Desktop startup aborted: %s", message)
        _show_windows_error_dialog("Diaricat - Runtime requerido", message)
        return

    host = settings.app.host
    port = settings.app.port
    if not _is_bindable(host, port):
        port = _find_available_port(host, port + 1)

    # ── 1. Show splash immediately — no server needed ─────────────────────────
    logo_uri = _resolve_logo_data_uri()
    splash_html = _make_splash_html(logo_uri)
    icon_path = _resolve_icon_path()
    api = WindowAPI()

    window = webview.create_window(
        title=" ",
        html=splash_html,
        width=1320,
        height=860,
        min_size=(900, 600),
        frameless=False,
        easy_drag=False,
        shadow=True,
        resizable=True,
        js_api=api,
        background_color="#06060d",
    )
    # NOTE: do NOT call api.set_window() here — HWND doesn't exist until
    # webview.start() runs. Styles are applied in _on_webview_started below.

    # ── 2. Start uvicorn in background (deferred imports for speed) ──────────
    def _boot_server():
        ctx = build_context()
        app = create_app(ctx)
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_config=None,
            access_log=False,
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None
        _boot_server.server = server
        server.run()

    _boot_server.server = None
    server_thread = threading.Thread(target=_boot_server, daemon=True, name="uvicorn")
    server_thread.start()

    # ── 3. Navigate to app once backend ready (non-blocking) ──────────────────
    nav_thread = threading.Thread(
        target=_wait_for_server_and_navigate,
        args=(host, port, window, 30.0),
        daemon=True,
        name="nav-watcher",
    )
    nav_thread.start()

    def _remove_titlebar_icon(hwnd: int) -> None:
        """Remove the small icon from the Windows title bar (keep taskbar icon)."""
        if os.name != "nt" or not hwnd:
            return
        try:
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, 0)
        except Exception:
            pass

    def _on_webview_started() -> None:
        """Called on the GUI thread once the native window exists."""
        api.set_window(window)
        _remove_titlebar_icon(api._get_hwnd() or 0)
        # Re-apply dark chrome after WinForms finishes init (prevents race with WinForms defaults)
        def _delayed_dark():
            import time as _time
            _time.sleep(0.45)
            api._apply_dark_window_chrome()
            _remove_titlebar_icon(api._get_hwnd() or 0)
        threading.Thread(target=_delayed_dark, daemon=True, name="dark-chrome-retry").start()

    webview.start(
        func=_on_webview_started,
        gui="edgechromium",
        icon=None,  # branding handled by FloatingBrand inside the webview
        debug=False,
    )

    # ── 4. Graceful shutdown ──────────────────────────────────────────────────
    logger.info("Desktop window closed — shutting down backend")
    if _boot_server.server is not None:
        _boot_server.server.should_exit = True
    server_thread.join(timeout=8)
    reset_context()
    logger.info("Diaricat shutdown complete (session=%s)", SESSION_ID)
