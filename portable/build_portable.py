r"""Build Peek & Grep Portable.

Output (in release\\):
    PeekGrep\\               the portable folder: runtime\\, app\\, PeekGrep.exe (launcher), README.txt
    PeekGrep.exe            one self-extracting file: on first start it unpacks PeekGrep\\ next to itself

Steps:
    1. Get the Python runtime:
       - without a venv (normal case, build.bat): copy vendor\runtime from the repository;
       - with backend\venv: trace which packages the app imports, copy a lean runtime
         (no tkinter, no pip) and only those packages. --update-vendor then refreshes vendor\runtime.
    2. Build the UI with npm if frontend\node_modules exists, else use the committed frontend\dist.
    3. Copy the app (desktop_app.py, backend\\app, frontend\\dist) and precompile it.
    4. Compile the C# launcher twice: plain, and with the zipped folder as an embedded resource.

Usage:
    build.bat                                   (uses vendor\runtime\python.exe, nothing to install)
    python build_portable.py [--venv <path>] [--skip-frontend] [--update-vendor]
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
RELEASE = PROJECT / "release"
CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
DEFAULT_VENV = PROJECT / "backend" / "venv"  # optional, only to update packages
VENDOR_RUNTIME = PROJECT / "vendor" / "runtime"  # committed runtime: builds need no pip and no Python install

# Always copied, even when the trace does not see them (lazy imports, shims)
EXTRA_PACKAGES = {"clr.py", "colorama", "multipart"}

RUNTIME_FILES = ["python.exe", "pythonw.exe", "python3.dll", "LICENSE.txt"]
DLL_SKIP = {"_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "winsound.pyd", "_remote_debugging.pyd", "python.cat"}
LIB_SKIP_DIRS = {"site-packages", "__pycache__", "idlelib", "tkinter", "turtledemo", "ensurepip", "test", "tests",
                 "pydoc_data", "venv", "_pyrepl", "lib2to3"}
LIB_SKIP_FILES = {"turtle.py"}
# Pillow parts that the app never uses (AVIF codec, FreeType text drawing); Pillow loads them only on demand
SITE_SKIP = ("__pycache__", "tests", "test", "_avif*.pyd", "_imagingft*.pyd")


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def base_python_home(venv: Path) -> Path:
    cfg = (venv / "pyvenv.cfg").read_text(encoding="utf-8")
    for line in cfg.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "home":
            return Path(value.strip())
    raise SystemExit("pyvenv.cfg has no 'home' entry")


def run(cmd, **kw) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        raise SystemExit(f"Command failed: {cmd}")
    return res.stdout


def build_frontend() -> None:
    """Build the UI with npm when it is available; else use the committed frontend/dist."""
    frontend = PROJECT / "frontend"
    if (frontend / "node_modules").is_dir() and shutil.which("npm"):
        log("Building frontend (npm run build)")
        run("npm run build", cwd=frontend, shell=True)
    elif (frontend / "dist" / "index.html").exists():
        log("No npm or node_modules: using the committed frontend/dist")
    else:
        raise SystemExit("frontend/dist is missing and npm is not available")


def copy_vendor_runtime(target: Path) -> None:
    log(f"Copying the committed runtime from {VENDOR_RUNTIME}")
    if not (VENDOR_RUNTIME / "pythonw.exe").exists():
        raise SystemExit("vendor/runtime is missing. Get the complete repository again.")
    shutil.copytree(VENDOR_RUNTIME, target, ignore=shutil.ignore_patterns("__pycache__"))


def update_vendor(runtime: Path) -> None:
    log("Updating vendor/runtime from this build")
    if VENDOR_RUNTIME.exists():
        shutil.rmtree(VENDOR_RUNTIME)
    shutil.copytree(runtime, VENDOR_RUNTIME, ignore=shutil.ignore_patterns("__pycache__"))


def copy_runtime(home: Path, venv: Path, target: Path) -> None:
    log(f"Copying Python runtime from {home}")
    target.mkdir(parents=True)
    for name in RUNTIME_FILES:
        shutil.copy2(home / name, target / name)
    for dll in home.glob("python3*.dll"):
        shutil.copy2(dll, target / dll.name)
    for dll in home.glob("vcruntime*.dll"):
        shutil.copy2(dll, target / dll.name)

    (target / "DLLs").mkdir()
    for f in (home / "DLLs").iterdir():
        if f.is_file() and f.name not in DLL_SKIP:
            shutil.copy2(f, target / "DLLs" / f.name)

    def ignore(dirpath, names):
        skip = set()
        for n in names:
            if n in LIB_SKIP_DIRS or n in LIB_SKIP_FILES:
                skip.add(n)
        return skip

    shutil.copytree(home / "Lib", target / "Lib", ignore=ignore)

    # Only the packages that the app imports
    site_src = venv / "Lib" / "site-packages"
    traced = json.loads(run([str(venv / "Scripts" / "python.exe"), str(HERE / "trace_imports.py"),
                             str(PROJECT), str(site_src)]).strip().splitlines()[-1])
    wanted = {t.lower() for t in traced} | {e.lower() for e in EXTRA_PACKAGES}
    site_dst = target / "Lib" / "site-packages"
    site_dst.mkdir()
    copied = []
    for entry in site_src.iterdir():
        if entry.name.lower() in wanted:
            if entry.is_dir():
                shutil.copytree(entry, site_dst / entry.name, ignore=shutil.ignore_patterns(*SITE_SKIP))
            else:
                shutil.copy2(entry, site_dst / entry.name)
            copied.append(entry.name)
    # Package metadata (some libraries read their own version at import time)
    for info in site_src.glob("*.dist-info"):
        record = info / "RECORD"
        if not record.exists():
            continue
        tops = {line.split(",")[0].split("/")[0].lower() for line in record.read_text(encoding="utf-8").splitlines() if line}
        if tops & wanted:
            shutil.copytree(info, site_dst / info.name)
    log(f"Packages: {', '.join(sorted(copied))}")

    # Isolated path list next to python3XX.dll: ignores PYTHONPATH, PYTHONHOME, the registry,
    # and the user site folder
    dll = next(p for p in target.glob("python3*.dll") if p.name != "python3.dll")
    (target / f"{dll.stem}._pth").write_text("Lib\nLib\\site-packages\nDLLs\n", encoding="utf-8")


def copy_app(target: Path) -> None:
    log("Copying app")
    target.mkdir(parents=True)
    shutil.copy2(PROJECT / "desktop_app.py", target / "desktop_app.py")
    shutil.copytree(PROJECT / "backend" / "app", target / "backend" / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(PROJECT / "frontend" / "dist", target / "frontend" / "dist")


def precompile(folder: Path) -> None:
    log("Precompiling .pyc files with the portable runtime")
    py = folder / "runtime" / "python.exe"
    run([str(py), "-m", "compileall", "-q", "-j", "0", str(folder / "runtime" / "Lib"), str(folder / "app")])


def smoke_test(folder: Path) -> None:
    log("Smoke test: import the app with the portable runtime only")
    py = folder / "runtime" / "python.exe"
    app_dir = folder / "app"
    code = f"""
import os, sys, socket, tempfile, threading, time, urllib.request
os.environ['PEEK_GREP_DATA'] = tempfile.mkdtemp(prefix='peekgrep-smoke-')
sys.path[:0] = [r'{app_dir}', r'{app_dir / "backend"}']
import desktop_app, uvicorn, webview.platforms.winforms, uvicorn.loops.auto, uvicorn.protocols.http.auto
s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(8); port = s.getsockname()[1]
srv = uvicorn.Server(uvicorn.Config(desktop_app.app, log_level='warning'))
threading.Thread(target=srv.run, kwargs={{'sockets': [s]}}, daemon=True).start()
# Direct calls: a company proxy must not get the 127.0.0.1 requests
direct = urllib.request.build_opener(urllib.request.ProxyHandler({{}}))
end = time.time() + 30  # antivirus scans can make the first start slow
while True:
    try:
        status = direct.open(f'http://127.0.0.1:{{port}}/api/status', timeout=3).read().decode()
        break
    except Exception:
        if time.time() > end:
            raise
        time.sleep(0.5)
print(status)
print(len(direct.open(f'http://127.0.0.1:{{port}}/', timeout=5).read()), 'bytes of index.html')
print('sys.path =', sys.path)
"""
    # A clean environment proves that nothing comes from the developer's Python setup
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    res = subprocess.run([str(py), "-c", code], env=env, capture_output=True, text=True)
    if res.returncode == 0:
        print(res.stdout)
        return
    # The exe is still built: the test checks this PC, not the files
    print(res.stdout)
    print(res.stderr[-3000:])
    log("WARNING: the smoke test failed on this PC (see the error above). The build continues.")


def make_icon(path: Path) -> None:
    from PIL import Image, ImageDraw
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, 248, 248], radius=60, fill=(20, 21, 27, 255), outline=(72, 78, 100, 255), width=6)
    d.ellipse([58, 50, 162, 154], outline=(124, 156, 255, 255), width=20)
    d.line([148, 142, 198, 192], fill=(124, 156, 255, 255), width=28)
    d.ellipse([186, 180, 210, 204], fill=(124, 156, 255, 255))
    img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def compile_launcher(out_exe: Path, payload: Path = None, version: str = "") -> None:
    src = HERE / "launcher" / "PeekGrepLauncher.cs"
    icon = HERE / "launcher" / "app.ico"
    manifest = HERE / "launcher" / "app.manifest"
    cmd = [str(CSC), "/nologo", "/target:winexe", "/optimize+", "/platform:anycpu",
           f"/out:{out_exe}", f"/win32icon:{icon}", f"/win32manifest:{manifest}",
           "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll",
           "/r:System.IO.Compression.dll", "/r:System.IO.Compression.FileSystem.dll"]
    if payload:
        version_file = payload.with_suffix(".version")
        version_file.write_text(version, encoding="utf-8")
        cmd += [f"/resource:{payload},payload.zip", f"/resource:{version_file},payload.version"]
    cmd.append(str(src))
    run(cmd)


def zip_folder(folder: Path, out_zip: Path) -> None:
    """Zip the runtime and app folders and README.txt. The .pyc caches stay out: Python writes them on the first start."""
    log("Packing payload zip")
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(folder.rglob("*")):
            rel = path.relative_to(folder).as_posix()
            if rel.split("/")[0] not in ("runtime", "app", "README.txt") or "__pycache__" in rel.split("/"):
                continue
            if path.is_file():
                zf.write(path, rel)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--venv", type=Path, default=DEFAULT_VENV)
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--update-vendor", action="store_true", help="copy the new runtime into vendor/runtime")
    args = parser.parse_args()
    use_venv = (args.venv / "Scripts" / "python.exe").exists()

    started = time.time()
    if not args.skip_frontend:
        build_frontend()

    folder = RELEASE / "PeekGrep"
    if RELEASE.exists():
        shutil.rmtree(RELEASE)
    folder.mkdir(parents=True)

    if use_venv:
        copy_runtime(base_python_home(args.venv), args.venv, folder / "runtime")
        if args.update_vendor:
            update_vendor(folder / "runtime")
    else:
        copy_vendor_runtime(folder / "runtime")
    copy_app(folder / "app")
    shutil.copy2(HERE / "README.txt", folder / "README.txt")
    precompile(folder)
    smoke_test(folder)

    log("Compiling launchers")
    icon = HERE / "launcher" / "app.ico"
    if not icon.exists():
        make_icon(icon)
    compile_launcher(folder / "PeekGrep.exe")

    payload = RELEASE / "payload.zip"
    zip_folder(folder, payload)
    digest = hashlib.sha1(payload.read_bytes()).hexdigest()[:12]
    version = f"3.0.0+{digest}"
    compile_launcher(RELEASE / "PeekGrep.exe", payload=payload, version=version)
    payload.unlink()
    payload.with_suffix(".version").unlink()

    size_mb = lambda p: sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6  # noqa: E731
    log(f"Folder: {folder} ({size_mb(folder):.1f} MB)")
    log(f"Single exe: {RELEASE / 'PeekGrep.exe'} ({(RELEASE / 'PeekGrep.exe').stat().st_size / 1e6:.1f} MB), version {version}")
    log(f"Done in {time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
