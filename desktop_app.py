"""Peek & Grep Portable: desktop window, tray icon, and global hotkey.

Runs the FastAPI search engine in a background thread on a free local port, serves the
React interface, and opens a frameless WebView2 window. Everything the app writes goes
into the portable data folder. It writes nothing to the registry, except the optional
Start with Windows entry below, and nothing to the Startup folder.

Command line:
    --hidden    start in the tray without showing the window

Start with Windows (off by default, in the app's settings or the tray menu) adds one value to
HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run; turning it off removes it again.
"""

import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import zlib
from pathlib import Path

# Add backend directory to sys.path so 'app' imports seamlessly
CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CURRENT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import APP_HOME, APP_VERSION, DATA_DIR, LOG_PATH  # noqa: E402

APP_TITLE = "Peek & Grep"
INSTANCE_FILE = DATA_DIR / "instance.json"

# Calls to our own server go direct. A company proxy (environment or Windows settings)
# would otherwise get the 127.0.0.1 requests and refuse them.
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# The window only loads pages from 127.0.0.1. These switches stop WebView2's own background
# calls (Edge configuration downloads) and the WPAD proxy lookup.
# ElasticOverscroll is the switch that pywebview sets itself (one --disable-features list only).
# Do not add NetworkErrorLogging to that list: in WebView2 155 it makes the browser process
# use a full CPU core all the time (measured 2026-10-21).
WEBVIEW2_ARGS = (
    "--disable-background-networking --no-proxy-server "
    "--disable-features=ElasticOverscroll"
)
DEFAULT_SIZE = (880, 620)
MIN_SIZE = (560, 420)


def message_box(text: str, title: str = APP_TITLE, flags: int = 0x40) -> int:
    """Native Windows message box (0x40 = information icon)."""
    try:
        return ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        print(f"[{title}] {text}")
        return 0


def prepare_data_dir() -> None:
    """Create the data folder, or stop with a clear message if the folder is read-only."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = DATA_DIR / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception as e:
        message_box(
            f"Peek & Grep cannot write to its data folder:\n{DATA_DIR}\n\n{e}\n\n"
            "Copy the Peek & Grep folder to a place where you can write files, then start it again.",
            flags=0x10,
        )
        sys.exit(1)


def redirect_output() -> None:
    """pythonw.exe has no console: write output to data\\app.log (kept below 2 MB)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        log = Path(LOG_PATH)
        if log.exists() and log.stat().st_size > 2 * 1024 * 1024:
            log.replace(log.with_suffix(".log.1"))
        fp = open(log, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or fp
        sys.stderr = sys.stderr or fp
    except Exception:
        pass


prepare_data_dir()
redirect_output()

import keyboard  # noqa: E402
import pystray  # noqa: E402
import uvicorn  # noqa: E402
import webview  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app.main import (  # noqa: E402
    app,
    set_get_window_size_callback,
    set_hide_window_callback,
    set_autostart_callback,
    set_hotkey_callback,
    set_open_data_folder_callback,
    set_pick_folders_callback,
    set_quit_callback,
    set_resize_window_callback,
    set_show_window_callback,
    set_toggle_maximize_callback,
)
from app.screens import place_window  # noqa: E402
from app.state import index_manager, settings_store  # noqa: E402

# Global State
window_visible = False
main_window = None
tray_icon = None
server_port = 0
is_maximized_state = False
last_window_size = DEFAULT_SIZE
last_position = None            # (x, y) of the last window, reused when the window opens again
show_requested = threading.Event()
quitting = False
pending_js: list = []           # scripts for the next page load (for example "open the folders panel")
target_url = ""
_mutex_handle = None
_hotkey_handle = None           # the registered global show/hide key


# -- single instance ---------------------------------------------------------------

def acquire_single_instance() -> bool:
    """One app per data folder. A second start shows the running window and exits."""
    global _mutex_handle
    name = "Local\\PeekGrepPortable-" + format(zlib.crc32(str(DATA_DIR).lower().encode("utf-8")), "08x")
    kernel32 = ctypes.windll.kernel32
    _mutex_handle = kernel32.CreateMutexW(None, False, name)
    ERROR_ALREADY_EXISTS = 183
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def signal_running_instance() -> bool:
    try:
        info = json.loads(INSTANCE_FILE.read_text(encoding="utf-8"))
        req = urllib.request.Request(f"http://127.0.0.1:{info['port']}/api/actions/show-window",
                                     data=b"", method="POST")
        LOCAL_HTTP.open(req, timeout=2).read()
        return True
    except Exception as e:
        print(f"[Desktop App] Could not reach the running instance: {e}")
        return False


# -- backend -----------------------------------------------------------------------

def open_server_socket() -> socket.socket:
    """Bind a free port on 127.0.0.1 (no fixed port, so no conflict with other apps)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    return sock


def start_backend_server(sock: socket.socket) -> None:
    """Run FastAPI with Uvicorn on the bound socket."""
    config = uvicorn.Config(app=app, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    server.run(sockets=[sock])


def wait_for_backend(port: int, timeout: float = 45.0) -> bool:
    """Poll backend until operational or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with LOCAL_HTTP.open(f"http://127.0.0.1:{port}/api/status", timeout=1.0) as res:
                if res.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


# -- window ------------------------------------------------------------------------

def resize_window(width: int, height: int):
    """Resize the window to given dimensions."""
    global is_maximized_state, last_window_size
    if main_window:
        w = max(MIN_SIZE[0], int(width))
        h = max(MIN_SIZE[1], int(height))
        main_window.resize(w, h)
        last_window_size = (w, h)
        is_maximized_state = False


def toggle_maximize() -> bool:
    """Toggle the maximized state of the window."""
    global is_maximized_state, last_window_size
    if main_window:
        try:
            if not is_maximized_state:
                last_window_size = (main_window.width, main_window.height)
                main_window.maximize()
                is_maximized_state = True
            else:
                main_window.restore()
                main_window.resize(*last_window_size)
                is_maximized_state = False
        except Exception as e:
            print(f"[Desktop App] Error toggling maximize: {e}")
    return is_maximized_state


def get_window_size() -> dict:
    if main_window:
        try:
            return {"width": main_window.width, "height": main_window.height, "is_maximized": is_maximized_state}
        except Exception:
            pass
    return {"width": DEFAULT_SIZE[0], "height": DEFAULT_SIZE[1], "is_maximized": False}


VK_MENU = 0x12  # Alt
VK_MASK = 0xE8  # an unassigned key (AutoHotkey's "menu mask key")
KEYEVENTF_KEYUP = 0x2
_focus_api = None


def _user32():
    """user32 with typed window handles (a copy, so pywebview's own calls are not affected)."""
    global _focus_api
    if _focus_api is None:
        from ctypes import wintypes

        api = ctypes.WinDLL("user32")
        hwnd = wintypes.HWND
        for name, args, res in (
            ("GetForegroundWindow", [], hwnd),
            ("GetWindowThreadProcessId", [hwnd, ctypes.c_void_p], wintypes.DWORD),
            ("AttachThreadInput", [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL], wintypes.BOOL),
            ("IsIconic", [hwnd], wintypes.BOOL),
            ("ShowWindow", [hwnd, ctypes.c_int], wintypes.BOOL),
            ("BringWindowToTop", [hwnd], wintypes.BOOL),
            ("SetForegroundWindow", [hwnd], wintypes.BOOL),
            ("GetAsyncKeyState", [ctypes.c_int], ctypes.c_short),
            ("keybd_event", [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p], None),
            ("FindWindowW", [wintypes.LPCWSTR, wintypes.LPCWSTR], hwnd),
        ):
            fn = getattr(api, name)
            fn.argtypes, fn.restype = args, res
        _focus_api = api
    return _focus_api


def _tap(vk: int) -> None:
    user32 = _user32()
    user32.keybd_event(vk, 0, 0, None)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, None)


def mask_modifier_release() -> None:
    """After a global key with Alt or Win, while that key is still down: an unassigned key
    press, so letting go of Alt does not open the window menu (the typing would then go
    nowhere) and letting go of Win does not open Start."""
    try:
        _tap(VK_MASK)
    except Exception:
        pass


def _window_handle() -> int:
    try:
        return int(main_window.native.Handle.ToInt64())
    except Exception:
        try:
            return _user32().FindWindowW(None, APP_TITLE) or 0
        except Exception:
            return 0


def _focus_webview() -> None:
    """Give the page the keyboard: focus the WebView2 control inside the window."""
    try:
        from System import Func, Type  # pythonnet, loaded by pywebview

        form = main_window.native
        form.Invoke(Func[Type](lambda: form.webview.Focus() and None))
    except Exception:
        pass


def focus_window_native() -> bool:
    """Make the window the active one, with the keyboard in the page.

    Windows refuses a plain SetForegroundWindow from an app in the background (the window
    then opens behind or without the keyboard). The call works while this thread is attached
    to the input of the active window; a masked Alt press is the last resort.
    """
    try:
        user32 = _user32()
        kernel32 = ctypes.windll.kernel32
        hwnd = _window_handle()
        if not hwnd:
            return False
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        foreground = user32.GetForegroundWindow()
        if foreground != hwnd:
            me = kernel32.GetCurrentThreadId()
            other = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
            attached = bool(other) and other != me and bool(user32.AttachThreadInput(me, other, True))
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(me, other, False)
        if user32.GetForegroundWindow() != hwnd:
            held = user32.GetAsyncKeyState(VK_MENU) & 0x8000
            if not held:
                user32.keybd_event(VK_MENU, 0, 0, None)
            user32.SetForegroundWindow(hwnd)
            _tap(VK_MASK)
            if not held:
                user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, None)
        _focus_webview()
        return user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


# -- screens -----------------------------------------------------------------------
# The window opens on a screen that is on: the screen with the mouse pointer. A remembered
# position on another screen (or on a screen that was switched off or unplugged) is moved
# there, with the same place on the screen, and the size is kept inside the screen.

class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT), ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]


def _screen_scale() -> float:
    """Logical-to-physical scale that pywebview uses for this (system DPI aware) process."""
    try:
        return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
    except Exception:
        return 1.0


def _work_area(x: int, y: int, nearest: bool):
    """(monitor handle, (left, top, right, bottom)) of the screen at a physical point."""
    try:
        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        user32.MonitorFromPoint.argtypes = [_POINT, ctypes.c_ulong]
        monitor = user32.MonitorFromPoint(_POINT(int(x), int(y)), 2 if nearest else 0)
        if not monitor:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info)):
            return None
        r = info.rcWork
        return monitor, (r.left, r.top, r.right, r.bottom)
    except Exception:
        return None


def _cursor_area():
    try:
        pt = _POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return _work_area(pt.x, pt.y, nearest=True)
    except Exception:
        pass
    return None


def window_placement(position, size):
    """Where the window opens: ((x, y), (width, height)) in logical pixels, or None for the default."""
    scale = _screen_scale()
    target = _cursor_area() if settings_store.open_on_mouse_monitor else None
    current = nearest = None
    if position:
        cx = position[0] * scale + size[0] * scale / 2
        cy = position[1] * scale + size[1] * scale / 2
        current = _work_area(cx, cy, nearest=False)
        nearest = _work_area(cx, cy, nearest=True)
    return place_window(position, size, scale, target, current, nearest)


def _place_hidden_window() -> None:
    """Move a hidden (not released) window to the screen with the mouse pointer before it shows."""
    if not main_window or is_maximized_state:
        return
    try:
        placed = window_placement((main_window.x, main_window.y), (main_window.width, main_window.height))
        if not placed:
            return
        (x, y), (w, h) = placed
        if (w, h) != (main_window.width, main_window.height):
            main_window.resize(w, h)
        if (x, y) != (main_window.x, main_window.y):
            main_window.move(x, y)
    except Exception as e:
        print(f"[Desktop App] Could not place the window: {e}")


def show_window():
    """Show the window and focus the search input. Opens a new window if it was released."""
    global window_visible
    if main_window is None:
        show_requested.set()  # the main loop creates the window
        return
    if main_window:
        try:
            if not window_visible:
                _place_hidden_window()
            main_window.show()
            main_window.restore()
            window_visible = True
            focus_window_native()
            main_window.evaluate_js("window.dispatchEvent(new CustomEvent('peekgrep:shown'))")
        except Exception as e:
            print(f"[Desktop App] Error showing window: {e}")


def _page_is_editing() -> bool:
    """True when Quick Look has an open editor (the window must then only hide, not close)."""
    try:
        return bool(main_window.evaluate_js("document.body.dataset.editing === '1'"))
    except Exception:
        return True


def _remember_geometry() -> None:
    global last_window_size, last_position
    try:
        if not is_maximized_state:
            last_window_size = (main_window.width, main_window.height)
        last_position = (main_window.x, main_window.y)
    except Exception:
        pass


def hide_window():
    """Hide the window to the tray. By default the WebView closes to free its memory."""
    global window_visible
    if main_window is None:
        return
    window_visible = False
    if settings_store.release_window_on_hide and not _page_is_editing():
        _remember_geometry()
        try:
            main_window.destroy()  # webview.start() returns; the main loop waits for the next show
        except Exception as e:
            print(f"[Desktop App] Error closing window: {e}")
        return
    if main_window:
        try:
            main_window.hide()
            window_visible = False
            # The page polls less while it is in the tray
            main_window.evaluate_js("window.dispatchEvent(new CustomEvent('peekgrep:hidden'))")
        except Exception as e:
            print(f"[Desktop App] Error hiding window: {e}")


def toggle_window():
    if window_visible:
        hide_window()
    else:
        show_window()


def on_hotkey(hotkey: str) -> None:
    if any(mod in hotkey.split("+") for mod in ("alt", "windows")):
        mask_modifier_release()
    toggle_window()


def open_folders_panel():
    if main_window is None:
        pending_js.append("window.dispatchEvent(new CustomEvent('peekgrep:open-folders'))")
        show_window()
        return
    show_window()
    if main_window:
        try:
            main_window.evaluate_js("window.dispatchEvent(new CustomEvent('peekgrep:open-folders'))")
        except Exception:
            pass


def pick_folders() -> list:
    """Native multi-select folder dialog."""
    if not main_window:
        return []
    result = main_window.create_file_dialog(webview.FileDialog.FOLDER, allow_multiple=True)
    if not result:
        return []
    return [str(p) for p in (result if isinstance(result, (list, tuple)) else [result])]


def open_data_folder():
    subprocess.Popen(f'explorer.exe "{DATA_DIR}"')


def confirm_and_reindex(icon=None, item=None):
    folders = settings_store.folders()
    if not folders:
        open_folders_panel()
        return
    text = "Scan all working folders again?\n\n" + "\n".join(folders)
    if message_box(text, "Peek & Grep - Re-index", 1 | 0x20) == 1:  # OK / question icon
        index_manager.queue_scan()


def exit_application(icon=None, item=None):
    """Stop the tray icon, the window, and the background workers."""
    global quitting
    quitting = True
    show_requested.set()
    print("[Desktop App] Exiting Peek & Grep...")
    try:
        index_manager.stop()
    except Exception:
        pass
    try:
        INSTANCE_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    if tray_icon:
        try:
            tray_icon.stop()
        except Exception:
            pass
    if main_window:
        try:
            main_window.destroy()
        except Exception:
            pass
    os._exit(0)


class DesktopApi:
    """JS bridge exposed to the React frontend as window.pywebview.api."""

    def hide_window(self):
        hide_window()

    def show_window(self):
        show_window()

    def minimize(self):
        if main_window:
            main_window.minimize()

    def resize_window(self, width: int, height: int):
        resize_window(width, height)

    def toggle_maximize(self) -> bool:
        return toggle_maximize()

    def get_window_size(self) -> dict:
        return get_window_size()

    def pick_folders(self) -> list:
        return pick_folders()

    def open_data_folder(self):
        open_data_folder()

    def quit_app(self):
        threading.Timer(0.1, exit_application).start()


# -- start with Windows ----------------------------------------------------------------

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_name() -> str:
    """One value per copy of the app (per data folder), so two copies do not overwrite each other."""
    return "PeekGrepPortable-" + format(zlib.crc32(str(DATA_DIR).lower().encode("utf-8")), "08x")


def autostart_command(hidden: bool) -> str:
    """The plain launcher of this folder (with the app icon), or the runtime directly."""
    launcher = APP_HOME / "PeekGrep.exe"
    if launcher.exists():
        cmd = f'"{launcher}"'
    else:
        cmd = f'"{APP_HOME / "runtime" / "pythonw.exe"}" "{CURRENT_DIR / "desktop_app.py"}"'
    return cmd + (" --hidden" if hidden else "")


def set_autostart(enabled: bool, hidden: bool = True) -> None:
    """Add or remove this app's value in the Run key of the current user."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, autostart_name(), 0, winreg.REG_SZ, autostart_command(hidden))
        else:
            try:
                winreg.DeleteValue(key, autostart_name())
            except FileNotFoundError:
                pass
    print(f"[Desktop App] Start with Windows: {'on' if enabled else 'off'}")


def sync_autostart() -> None:
    """At every start: the entry follows the setting and the current folder (a moved folder or USB drive)."""
    try:
        set_autostart(settings_store.start_with_windows, settings_store.start_hidden)
    except Exception as e:
        print(f"[Desktop App] Could not update the startup entry: {e}")


def toggle_autostart(icon=None, item=None) -> None:
    enabled = not settings_store.start_with_windows
    try:
        set_autostart(enabled, settings_store.start_hidden)
        settings_store.set_app_settings({"start_with_windows": enabled})
    except Exception as e:
        message_box(f"Windows did not accept the startup entry:\n{e}", flags=0x10)


# -- tray and hotkey -----------------------------------------------------------------

def generate_tray_icon() -> Image.Image:
    """64x64 tray icon: a rounded dark tile with a blue lens."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([2, 2, 62, 62], radius=16, fill=(20, 21, 26, 255), outline=(70, 76, 96, 255), width=2)
    draw.ellipse([15, 13, 41, 39], outline=(124, 156, 255, 255), width=5)
    draw.line([37, 36, 49, 48], fill=(124, 156, 255, 255), width=7)
    return img


def hotkey_label() -> str:
    return settings_store.hotkey.title().replace("Windows", "Win")


def setup_tray():
    global tray_icon
    menu = pystray.Menu(
        pystray.MenuItem(lambda item: f"Show / hide ({hotkey_label()})", lambda: toggle_window(), default=True),
        pystray.MenuItem("Working folders...", lambda: open_folders_panel()),
        pystray.MenuItem("Re-index all folders...", confirm_and_reindex),
        pystray.MenuItem("Start with Windows", toggle_autostart, checked=lambda item: settings_store.start_with_windows),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Window size", pystray.Menu(
            pystray.MenuItem("Compact (880 x 620)", lambda: resize_window(880, 620)),
            pystray.MenuItem("Standard (1080 x 720)", lambda: resize_window(1080, 720)),
            pystray.MenuItem("Large (1360 x 860)", lambda: resize_window(1360, 860)),
        )),
        pystray.MenuItem("Open data folder", lambda: open_data_folder()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Peek & Grep", exit_application),
    )
    tray_icon = pystray.Icon("peek_grep_portable", generate_tray_icon(), f"{APP_TITLE} ({hotkey_label()})", menu)
    threading.Thread(target=tray_icon.run, daemon=True).start()


def register_hotkey(hotkey: str) -> None:
    """Use a new global show/hide key. The old key stays when Windows refuses the new one."""
    global _hotkey_handle
    # suppress=True keeps Windows from opening the active window's system menu
    handle = keyboard.add_hotkey(hotkey, on_hotkey, args=(hotkey,), suppress=True)
    if _hotkey_handle is not None:
        try:
            keyboard.remove_hotkey(_hotkey_handle)
        except Exception:
            pass
    _hotkey_handle = handle
    print(f"[Desktop App] Registered global hotkey: {hotkey}")
    if tray_icon:
        try:
            tray_icon.title = f"{APP_TITLE} ({hotkey.title()})"
            tray_icon.update_menu()
        except Exception:
            pass


def setup_global_hotkey():
    hotkey = settings_store.hotkey
    try:
        register_hotkey(hotkey)
    except Exception as e:
        print(f"[Desktop App] Could not register global hotkey {hotkey}: {e}")


def on_window_shown():
    global window_visible
    window_visible = True
    focus_window_native()


def on_window_loaded():
    while pending_js:
        try:
            main_window.evaluate_js(pending_js.pop(0))
        except Exception:
            pass
    # A new window (after the tray): the page is there now, so it gets the keyboard
    if window_visible:
        focus_window_native()


def create_main_window(hidden: bool = False) -> None:
    global main_window
    kwargs = {}
    size = last_window_size
    placed = window_placement(last_position, last_window_size)
    if placed:
        (x, y), size = placed
        kwargs = {"x": x, "y": y}
    elif last_position:
        kwargs = {"x": last_position[0], "y": last_position[1]}
    main_window = webview.create_window(
        title=APP_TITLE,
        url=target_url,
        width=max(MIN_SIZE[0], size[0]),
        height=max(MIN_SIZE[1], size[1]),
        min_size=MIN_SIZE,
        resizable=True,
        frameless=True,
        easy_drag=False,
        on_top=False,
        hidden=hidden,
        background_color="#0B0B0E",
        js_api=DesktopApi(),
        **kwargs,
    )
    main_window.events.shown += on_window_shown
    main_window.events.loaded += on_window_loaded


def main():
    global main_window, server_port, target_url

    print("==================================================")
    print(f"  PEEK & GREP PORTABLE {APP_VERSION}")
    print(f"  Data folder: {DATA_DIR}")
    print("==================================================")

    # Same pixel units as pywebview from the start (it sets this too), so screen math matches
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

    if not acquire_single_instance():
        if signal_running_instance():
            return
        print("[Desktop App] Stale instance lock. Starting anyway.")

    sock = open_server_socket()
    server_port = sock.getsockname()[1]
    threading.Thread(target=start_backend_server, args=(sock,), daemon=True).start()

    set_hide_window_callback(hide_window)
    set_show_window_callback(show_window)
    set_resize_window_callback(resize_window)
    set_toggle_maximize_callback(toggle_maximize)
    set_get_window_size_callback(get_window_size)
    set_pick_folders_callback(pick_folders)
    set_open_data_folder_callback(open_data_folder)
    set_quit_callback(exit_application)
    set_hotkey_callback(register_hotkey)
    set_autostart_callback(set_autostart)

    if not wait_for_backend(server_port):
        message_box("The search engine did not start. See app.log in the data folder.", flags=0x10)
        sys.exit(1)
    INSTANCE_FILE.write_text(json.dumps({"port": server_port, "pid": os.getpid()}), encoding="utf-8")
    print(f"[Desktop App] Backend is live on http://127.0.0.1:{server_port}/")

    setup_tray()
    setup_global_hotkey()
    sync_autostart()

    dist_index = CURRENT_DIR / "frontend" / "dist" / "index.html"
    target_url = f"http://127.0.0.1:{server_port}/" if dist_index.exists() else "http://127.0.0.1:5173/"

    # WebView2 reads this variable when it starts; values that the user set stay at the end
    extra = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"{WEBVIEW2_ARGS} {extra}".strip()

    # One window at a time. When it closes to the tray, webview.start() returns and the loop
    # waits; Alt+Space or the tray icon opens a new window.
    wait_first = "--hidden" in sys.argv and settings_store.setup_done
    while not quitting:
        if wait_first:
            show_requested.wait()
            show_requested.clear()
            wait_first = False
            if quitting:
                break
        print("[Desktop App] Opening WebView2 window...")
        create_main_window()
        webview.start(
            gui="edgechromium",
            debug=False,
            private_mode=False,
            storage_path=str(DATA_DIR / "webview"),
        )
        main_window = None
        if quitting:
            break
        print("[Desktop App] Window closed to the tray (WebView released).")
        show_requested.clear()
        wait_first = True
    exit_application()


if __name__ == "__main__":
    main()
