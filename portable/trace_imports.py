"""Import everything the app loads at run time and print the site-packages entries it used.

Run with the development venv's Python:
    venv\\Scripts\\python.exe trace_imports.py <app_dir> <site_packages_dir>
"""

import json
import os
import sys
import tempfile


def main() -> None:
    app_dir, site_packages = sys.argv[1], os.path.normcase(os.path.abspath(sys.argv[2]))
    os.environ["PEEK_GREP_DATA"] = tempfile.mkdtemp(prefix="peekgrep-trace-")
    sys.path.insert(0, app_dir)
    sys.path.insert(0, os.path.join(app_dir, "backend"))

    import desktop_app  # noqa: F401  (imports FastAPI app, uvicorn, pywebview, pystray, keyboard, PIL)

    # Modules that load lazily at run time
    import uvicorn.lifespan.on  # noqa: F401
    import uvicorn.loops.asyncio  # noqa: F401
    import uvicorn.loops.auto  # noqa: F401
    import uvicorn.protocols.http.auto  # noqa: F401
    import uvicorn.protocols.http.h11_impl  # noqa: F401
    import uvicorn.protocols.websockets.auto  # noqa: F401
    import anyio._backends._asyncio  # noqa: F401
    import webview.platforms.edgechromium  # noqa: F401
    import webview.platforms.winforms  # noqa: F401
    import pystray._win32  # noqa: F401
    import keyboard._winkeyboard  # noqa: F401
    import starlette.staticfiles  # noqa: F401
    import starlette.middleware.trustedhost  # noqa: F401
    import pypdf  # noqa: F401
    from PIL import Image
    Image.init()  # all image plugins

    tops = set()
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if not f:
            continue
        nf = os.path.normcase(os.path.abspath(f))
        if nf.startswith(site_packages + os.sep):
            rel = nf[len(site_packages) + 1:]
            tops.add(rel.split(os.sep)[0])
    print(json.dumps(sorted(tops)))


if __name__ == "__main__":
    main()
