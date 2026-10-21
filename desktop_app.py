"""Peek & Grep Portable: desktop window, tray icon, and global hotkey.

Runs the FastAPI search engine in a background thread on a free local port, serves the
React interface, and opens a frameless WebView2 window. Everything the app writes goes
into the portable data folder. It writes nothing to the registry or the Startup folder.

Command line:
    --hidden    start in the tray without showing the window
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

from app.config import APP_VERSION, DATA_DIR, LOG_PATH  # noqa: E402

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
    set_open_data_folder_callback,
    set_pick_folders_callback,
    set_quit_callback,
    set_resize_window_callback,
    set_show_window_callback,
    set_toggle_maximize_callback,
)
from app.state import index_manager, settings_store  # noqa: E402

# Global State
window_visible = False
main_window = None
tray_icon = None
server_port = 0
is_maximized_state = False
last_window_size = DEFAULT_SIZE
_mutex_handle = None


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


def focus_window_native():
    """Bring the window to the foreground (Windows can refuse this for background apps)."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, APP_TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def show_window():
    """Show the window and focus the search input."""
    global window_visible
    if main_window:
        try:
            main_window.show()
            main_window.restore()
            window_visible = True
            focus_window_native()
            main_window.evaluate_js("window.dispatchEvent(new CustomEvent('peekgrep:shown'))")
        except Exception as e:
            print(f"[Desktop App] Error showing window: {e}")


def hide_window():
    """Hide the window to the tray."""
    global window_visible
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


def open_folders_panel():
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


# -- tray and hotkey -----------------------------------------------------------------

def generate_tray_icon() -> Image.Image:
    """64x64 tray icon: a rounded dark tile with a blue lens."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([2, 2, 62, 62], radius=16, fill=(20, 21, 26, 255), outline=(70, 76, 96, 255), width=2)
    draw.ellipse([15, 13, 41, 39], outline=(124, 156, 255, 255), width=5)
    draw.line([37, 36, 49, 48], fill=(124, 156, 255, 255), width=7)
    return img


def setup_tray():
    global tray_icon
    hotkey = settings_store.hotkey.title()
    menu = pystray.Menu(
        pystray.MenuItem(f"Show / hide ({hotkey})", lambda: toggle_window(), default=True),
        pystray.MenuItem("Working folders...", lambda: open_folders_panel()),
        pystray.MenuItem("Re-index all folders...", confirm_and_reindex),
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
    tray_icon = pystray.Icon("peek_grep_portable", generate_tray_icon(), f"{APP_TITLE} ({hotkey})", menu)
    threading.Thread(target=tray_icon.run, daemon=True).start()


def setup_global_hotkey():
    hotkey = settings_store.hotkey
    try:
        # suppress=True keeps Windows from opening the active window's system menu
        keyboard.add_hotkey(hotkey, toggle_window, suppress=True)
        print(f"[Desktop App] Registered global hotkey: {hotkey}")
    except Exception as e:
        print(f"[Desktop App] Could not register global hotkey {hotkey}: {e}")


def on_window_shown():
    global window_visible
    window_visible = True


def main():
    global main_window, server_port

    print("==================================================")
    print(f"  PEEK & GREP PORTABLE {APP_VERSION}")
    print(f"  Data folder: {DATA_DIR}")
    print("==================================================")

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

    if not wait_for_backend(server_port):
        message_box("The search engine did not start. See app.log in the data folder.", flags=0x10)
        sys.exit(1)
    INSTANCE_FILE.write_text(json.dumps({"port": server_port, "pid": os.getpid()}), encoding="utf-8")
    print(f"[Desktop App] Backend is live on http://127.0.0.1:{server_port}/")

    setup_tray()
    setup_global_hotkey()

    dist_index = CURRENT_DIR / "frontend" / "dist" / "index.html"
    target_url = f"http://127.0.0.1:{server_port}/" if dist_index.exists() else "http://127.0.0.1:5173/"

    start_hidden = "--hidden" in sys.argv and settings_store.setup_done
    main_window = webview.create_window(
        title=APP_TITLE,
        url=target_url,
        width=DEFAULT_SIZE[0],
        height=DEFAULT_SIZE[1],
        min_size=MIN_SIZE,
        resizable=True,
        frameless=True,
        easy_drag=False,
        on_top=False,
        hidden=start_hidden,
        background_color="#0B0B0E",
        js_api=DesktopApi(),
    )
    main_window.events.shown += on_window_shown

    # WebView2 reads this variable when it starts; values that the user set stay at the end
    extra = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"{WEBVIEW2_ARGS} {extra}".strip()

    print("[Desktop App] Opening WebView2 window...")
    webview.start(
        gui="edgechromium",
        debug=False,
        private_mode=False,
        storage_path=str(DATA_DIR / "webview"),
    )
    exit_application()


if __name__ == "__main__":
    main()
