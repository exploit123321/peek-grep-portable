# Peek & Grep Portable 3.0

A portable copy of Peek & Grep (original: `D:\New folder\peek-grep`, not changed).
It searches file names and the text inside files, with a Quick Look preview. It reads only
the working folders that the user selects on the first start.

## What changed from the original

- **Portable:** a bundled, isolated Python 3.14 runtime (`runtime\`, with a `._pth` file). All state is in `data\` next to the app. No registry entries (only the optional Start with Windows entry), no Startup shortcut. A free local port instead of 8000. One app per data folder: a second start shows the open window.
- **Working folders first:** nothing is scanned, watched, previewed, or opened outside the allowed folders. The API returns 403 for other paths. Removing a folder deletes its index entries. A full rescan also removes deleted files. A changed file goes back to the text queue. Same-drive folders follow a new USB drive letter.
- **Security:** no CORS, a host-name check, a CSP without inline scripts, HTML-escaped snippets, sanitized Markdown and EPUB HTML, and sandboxed raw files.
- **New UI** (React, Tailwind, no new packages). See the motion references below.

## Smart search

Without `:` the search looks at **file names only**. After `:` it looks at the **text inside
the files**. Everything is case-insensitive. The chips under the search field show how a search
was read, and the **?** button in the search field lists these examples.

| Type | Finds |
|---|---|
| `invoice` | File names that contain "invoice": invoice1.xlsx, invoice2.xlsx, old invoice.docx |
| `invoice.xlsx` | Exactly the file name invoice.xlsx (a name with an extension is the whole name) |
| `.xlsx` | All `.xlsx` files |
| `invoice+.xlsx` | Names with "invoice", only `.xlsx` files |
| `invoice-.xlsx` | Names with "invoice", but no `.xlsx` files |
| `invoice-old` | Names with "invoice" but without "old" |
| `:invoice` | "invoice" in the text of any file |
| `.xlsx:total` | "total" in the text of `.xlsx` files |
| `invoice+.xlsx:total` | "total" in the text of `.xlsx` files with "invoice" in the name |
| `invoice-old+.xlsx+.pdf:total` | "total" in `.xlsx` and `.pdf` files whose names have "invoice" and not "old" (invoiceold.pdf is left out) |
| `:annual review` | The words next to each other, in this order (only spaces or line breaks between them) |
| `:total+memo`, `:total-draft` | Texts with both words anywhere; texts with "total" but not "draft" |
| `-notes:total` | "total" in the text of files without "notes" in the name |
| `[invoice, receipt]` | One expandable row per element, each with all its hits. Spaces after the comma do not matter |
| `.xlsx:[total, tax]` | Text around the brackets applies to every element (`[invoice, receipt]+.pdf` too) |
| `tot*l`, `rec?ipt` | Wildcards: `*` any characters, `?` one character (in text: inside a word) |
| `/e-mail`, `"e-mail"` | `/` (the rest) or quotes: literal text. Works everywhere: `invoice:/total+tax` |
| `invoice;dm 2024;size>1mb` | Filters after `;` (dates and size, below) |

`+` (and outside brackets `,`) joins parts that must all hit; `-` starts a part that must not hit.
A `-` between two digits (`2024-05`) is just a character; for other names with a dash use `/` or
quotes. Several extensions mean any of them. Inside brackets a `/` literal ends at the next comma
or `]`, and everywhere at the next `;`. `C:\...` is a path, not a `:` search. All results can be
scrolled: the next hits load while you scroll.

### Filters: dates and size (after `;`)

Each `;` starts a filter; filters apply to every group. `dm` is the date modified, `dc` created,
`da` accessed (`modified`, `created`, `accessed` work too), `size` the file size.

| Type | Finds |
|---|---|
| `;dm from 01-03-2024 to 31-03-2024` | Modified in March 2024; both days count |
| `;dc from 2023` | Created on 1 January 2023 or later (no end) |
| `;da to 15-06` | Accessed on 15 June this year or before (no start; the whole day counts) |
| `;dm 2024-05`, `;dm may 2024`, `;dm 2024` | Modified in that month or year |
| `;dm 01.03.2024..15.03.2024`, `;dm 01-03-2024 - 15-03-2024` | Ranges without "from" |
| `;dm before 2020`, `;dm after 31-12-2025`, `;dm >=2025` | Before or after a date (`<`, `<=`, `>`, `>=`, `=`) |
| `;dm 7d`, `;dm since 2w`, `;dm >3m` | In the last 7 days, the last 2 weeks; older than 3 months (h, d, w, m, y) |
| `;dm today`, `yesterday`, `this week`, `last month`, `this year` | Named periods |
| `;size>10mb`, `;size<=1.5 gb`, `;size<500kb` | Sizes in b, kb, mb, gb, tb (1 kb = 1024 bytes; `1,5` works too) |
| `;size from 1mb to 50mb`, `;size 1mb..50mb` | Size ranges, both ends included |
| `;size=10mb` | About 10 MB (9.5 to 10.5 MB) |
| `;size small` | Windows size names: empty, tiny, small, medium, large, huge, gigantic |

Dates: `15-03-2024`, `15.03.2024`, `15/03/24`, `2024-03-15`, `20240315`, `15-03` (this year),
`03-2024`, `2024-03`, `2024`, and month names in English or Latvian (`15 mar 2024`,
`march 2024`, `15. marts 2024`). Numbers are read day-month-year; month-day-year and year first
can be chosen in the search settings, and a date that only works the other way round (like
`03/15/2024`) is read that way. A filter that cannot be read shows as a red chip and is left out.
The created and accessed dates come from the next scan after the update; Windows may not keep
accessed dates up to date (it is a Windows setting).

**Search settings** (… menu > Search settings, or Ctrl+.): everything above can be changed.

- **Smart search on or off:** the **Smart** button in the search field, or Alt+S. Off: the
  search field is plain text; no sign has a meaning and nothing is a filter.
- **Words search in:** file names (default), the text inside files, or names and text. This also
  applies when smart search is off.
- **Signs:** every sign can be another punctuation character or turned off (empty): text `:`,
  every part `+`, leave out `-` (anywhere, or only at a word start like `memo -draft`),
  literal `/`, groups `[` `,` `]`, filters `;`. A sign can have only one meaning; the panel says
  when two clash. Dates can be read day-month-year, month-day-year, or year first.
- **Rules:** `.xlsx` as a type filter, `invoice.xlsx` as the whole name, wildcards, quotes, comma
  outside a group, names that also match folder names, text words that match word beginnings.
- **Results:** order (best match, newest, oldest, name, size), rows per page, the wait after
  typing, text snippets, the chips, and whether groups start open.
- **Pasting cells from Excel:** open the table, search at once, or paste as text; values in file
  names or text; expandable rows or together.
- **Quick Look:** mark the hits, scroll to the first hit, typing starts Find.
- **Presets:** Smart (default), Smart with words in names and text, Classic (names and text, no
  special characters), File names only (no special characters), Smart with words in the text.

**Search a list:** paste cells from Excel (several rows or columns) into the search field, or
press Ctrl+L. A table opens: edit, remove, or add values, choose **File names** or **Text**, and
**Expandable** (one row per value, `[a, b]`) or **Together** (every value must hit, `a+b`).
"Only files" limits the files first, for example `.xlsx` or `invoice-old+.pdf`. The values stay on
screen under the search field, with their hit counts. Cells pasted into the table (also into a value)
become separate values, and **Split** turns a value with spaces into one value per word.

**Find in Quick Look:** Ctrl+F, or just start typing. Wildcards and `a+b` work there too.
Enter and Shift+Enter (or F3 and Shift+F3) go to the next and previous hit. PDFs use the
viewer's own search (plain text).

## Editing (Quick Look > Edit)

| Format | What you can edit |
|---|---|
| Text, code, Markdown, `.ini`, `.log` | All text. Encoding, BOM, and line ends are kept. |
| `.csv` `.tsv` | Cells, add and remove rows. The separator and encoding are kept. |
| `.xlsx` `.xlsm` | Cell values in the whole sheet (preview limit: 300,000 rows, 200 columns). Formatting, other sheets, and macros stay. Formula cells are locked. |
| `.docx` | Paragraph and table-cell text. Unchanged paragraphs stay exactly as they are. Paragraphs with pictures, links, fields, or tracked changes are locked. |
| `.doc` `.xls` `.ppt` | Not editable (use Open). |

A save refuses a file that changed on disk since you opened it, and fails safely when the file is open in another program. Ctrl+S saves, Esc leaves edit mode. The new text is in the index at once, so a search finds it right after the save, and the results refresh.

**Backups.** Before a save, the old version is copied to `data\backups\<file name> (<code>)\` (the code tells apart files with the same name in different folders). There is one backup per editing session, not one per save: more saves of the same file within an hour make no new backup, so the backup keeps the version from before your edits. A file that another program changed in the meantime is always backed up first. The 3 newest backups of each file are kept (200 in all). Change this in **… > Settings > Backups when you save an edit**: off, a new backup at every save / 10 min / 1 hour / 1 day, how many to keep per file, and buttons to open the folder or delete all backups.

## Settings (`data\settings.json`)

| Key | Default | Meaning |
|---|---|---|
| `hotkey` | `"alt+space"` | Global key that shows or hides the window |
| `shortcuts` | (none) | In-app keys that you changed, for example `{"move_down": ["ArrowDown", "J"]}`. Missing actions use the defaults |
| `search` | (none) | Search settings that you changed (see Search settings above), for example `{"enabled": false}` or `{"default_scope": "both", "and_char": "&"}` |
| `open_on_mouse_monitor` | `true` | Open the window on the screen with the mouse pointer. A remembered position on a screen that is off or unplugged is never used |
| `start_with_windows` | `false` | Start when you sign in to Windows: one value for your user in `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, kept up to date when the folder moves, removed when you turn it off |
| `start_hidden` | `true` | When Windows starts the app: stay in the tray (`true`) or open the window |
| `release_window_on_hide` | `true` | Close the WebView while the app is in the tray: about 110 MB instead of 300 MB; the window opens again at once |
| `backups` | `{"enabled": true, "per_file": 3, "gap_minutes": 60}` | Backups when the editor saves: on/off, how many are kept per file (1–50), and the minutes in which more saves make no new backup (0 = a backup at every save) |
| `skip_folders` | system and tool folders | Folder names that are never scanned, for example `["node_modules", ".git", "appdata"]`. Folders that start with `$` are always skipped. |

Change these in the app: **… > Settings** (start with Windows, the window, backups), **Search settings**, and
**Keyboard shortcuts**. Start with Windows is also in the tray menu.

Change the keys in the app: **… > Keyboard shortcuts** (Ctrl+,). Every key of the app can be
changed there, also the global show/hide key, and the app saves them in this file at once.
Quit the app before you edit this file by hand.

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

Tests (123): in `backend\`, run `venv\Scripts\python.exe -m pytest -q`.

## Motion references (from the motion reference matrix)

| UI part | Motion | Matrix reference |
|---|---|---|
| Search field, result list | Command palette, one highlight glides between rows | R41 Command Menu (M1, Q1) |
| Folder scope chip | Breadcrumb chip with a stacked layer behind the bar, Backspace leaves the scope | R23 вЊK Breadcrumbs (Q2) |
| Mode and type switches | Sliding pill, labels invert under the pill | R05 Exclusion Tabs (Q2) |
| Groups of `[a, b]` | Rows open like drop-downs, the files rise in | X04 result rows (E1, M1) |
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
