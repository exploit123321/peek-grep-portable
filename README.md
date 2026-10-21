# Peek & Grep Portable 3.0

A portable copy of Peek & Grep (original: `D:\New folder\peek-grep`, not changed).
It searches file names and the text inside files, with a Quick Look preview. It reads only
the working folders that the user selects on the first start.

## What changed from the original

- **Portable:** a bundled, isolated Python 3.14 runtime (`runtime\`, with a `._pth` file). All state is in `data\` next to the app. No registry entries, no Startup shortcut. A free local port instead of 8000. One app per data folder: a second start shows the open window.
- **Working folders first:** nothing is scanned, watched, previewed, or opened outside the allowed folders. The API returns 403 for other paths. Removing a folder deletes its index entries. A full rescan also removes deleted files. A changed file goes back to the text queue. Same-drive folders follow a new USB drive letter.
- **Security:** no CORS, a host-name check, a CSP without inline scripts, HTML-escaped snippets, sanitized Markdown and EPUB HTML, and sandboxed raw files.
- **New UI** (React, Tailwind, no new packages). See the motion references below.

## Build (nothing to install)

1. Get the repository (`git clone`, or "Code > Download ZIP" on GitHub).
2. Double-click `build.bat`.
3. The result is `release\PeekGrep.exe`.

The repository holds everything that the build needs:

- `vendor\runtime\`: the Python 3.14 runtime with all app packages (no pip needed).
- `frontend\dist\`: the built UI (no npm needed).
- The launcher is compiled with the C# compiler that is part of Windows (.NET Framework 4).

To change the program, edit the `.py` files in `backend\app\` or `desktop_app.py`, then run `build.bat` again.

## Optional: change the UI or the packages

- **UI** (`frontend\src`): needs Node.js. Run `npm ci` once in `frontend\`. After that, `build.bat` also rebuilds `frontend\dist`. Commit the new `dist`.
- **Packages:** needs Python from python.org and pip. Create `backend\venv`, install `backend\requirements.txt`, then run `backend\venv\Scripts\python.exe portable\build_portable.py --update-vendor` to refresh `vendor\runtime`.

Output in `release\`:

- `PeekGrep.exe` is one self-extracting file (about 39 MB). On the first start it unpacks `PeekGrep\` next to itself. Later starts launch at once. A newer exe replaces `runtime\` and `app\` and keeps `data\`.
- `PeekGrep\` is the unpacked portable folder (about 104 MB), with a plain launcher.

Tests (41): in `backend\`, run `venv\Scripts\python.exe -m pytest -q`.

## Motion references (from the motion reference matrix)

| UI part | Motion | Matrix reference |
|---|---|---|
| Search field, result list | Command palette, one highlight glides between rows | R41 Command Menu (M1, Q1) |
| Folder scope chip | Breadcrumb chip with a stacked layer behind the bar, Backspace leaves the scope | R23 ⌘K Breadcrumbs (Q2) |
| Mode and type switches | Sliding pill, labels invert under the pill | R05 Exclusion Tabs (Q2) |
| Mode and type switches | Soft light follows the pointer | R38 Flashlight Tabs (Q2) |
| Selected row | Accent prefix, rows away from the selection fade | E14 Slot scroll list (F2) |
| New result rows | Rise and sharpen in sequence | X04 result rows (E1, M1), R03 Blur Reveal (L2) |
| Quick Look | Grows out of the row, sharpens from a blur | R03 Blur Reveal (L2) |
| Setup stepper | Check circles, the line fills | Y20 four-step stepper (D2) |
| Folder rows | Box fills, check draws | R28 Animated Checkboxes (E1, P1) |
| Indexing rows | "scanning" with spinner, then a check and the count | E19 working rows (E1, I1, M1), X04 |
| Counters | Digits roll | R29 Countdown (I2) |
| Setup heading | Text decodes from glyphs | R24 Cryptic List (E2, L2) |
| Remove folder, re-index all | Hold to confirm, fill grows | R12 Hold Enter to confirm (P2) |
| Toasts, menus | Small cards rise in | Row R2 popovers and toasts (X09) |
