# Third-party software

Peek & Grep Portable's own code is in this repository (`backend/`, `frontend/src/`, `desktop_app.py`,
`portable/`) and is licensed under the MIT License ([`LICENSE`](LICENSE)). The MIT License covers
only that code; the parts below keep their own licences. The portable app (`vendor/runtime`, `frontend/dist`, and `PeekGrep.exe`) also contains
the software below. Each part keeps its own licence. The licence texts are in
[`third_party/licenses`](third_party/licenses) and, for Python packages, in each package's
`.dist-info` folder in `vendor/runtime/Lib/site-packages`. The built app has the same files in its
folder (`THIRD_PARTY_NOTICES.md` and `third_party\`, next to `PeekGrep.exe`).

## GPL and LGPL components: source code included

HEIC photos are decoded with pillow-heif. Its Windows build uses libheif, libde265, and x265 (built
by MSYS2 with the MinGW-w64 GCC toolchain). x265 is licensed under the GPL version 2, so these
binaries as a whole are distributed under the GPL version 2 (see
[`pillow-heif-bundled-libraries.txt`](third_party/licenses/pillow-heif-bundled-libraries.txt)).

The complete source code of these binaries, with the scripts used to build them, is in
[`third_party/sources`](third_party/sources), wherever the binaries are: in this repository and
inside `PeekGrep.exe` (`third_party\sources` in the app folder).

| Component | Version | Licence | Files in the app | Source |
|---|---|---|---|---|
| x265 | 4.3 (MSYS2 `mingw-w64-x265` 4.3-1) | GPL-2.0-or-later | `libx265-*.dll` | `x265-4.3.tar.gz` (tag 4.3, commit e9b88125), `msys2-build-scripts-*.tar.gz` |
| libde265 | 1.1.3 (MSYS2 `mingw-w64-libde265` 1.1.3-1) | LGPL-3.0-or-later | `libde265-*.dll` | `libde265-1.1.3.tar.gz` (tag v1.1.3, commit ba62bf4c), `msys2-build-scripts-*.tar.gz` |
| libheif | 1.23.6 | LGPL-3.0-or-later | `libheif-*.dll` | `libheif-1.23.6.tar.gz` (tag v1.23.6, commit f81f28ac), built by `libheif/windows/mingw-w64-libheif/PKGBUILD` in the pillow-heif source |
| pillow-heif | 1.8.1 | BSD-3-Clause (source); its Windows binaries as a whole GPL-2.0 | `pillow_heif/`, `_pillow_heif.cp314-win_amd64.pyd` | `pillow_heif-1.8.1-src.tar.gz` (the PyPI source release without its test images) |
| GCC runtime (MinGW-w64) | from MSYS2 | GPL-3.0-or-later with the GCC Runtime Library Exception 3.1 | `libgcc_s_seh-1-*.dll`, `libstdc++-6-*.dll` | https://gcc.gnu.org (MSYS2 `mingw-w64-gcc`) |
| winpthreads (MinGW-w64) | from MSYS2 | MIT | `libwinpthread-1-*.dll` | https://www.mingw-w64.org |
| pystray | 0.19.5 | LGPL-3.0-or-later | `site-packages/pystray/` (Python source) | the installed `.py` files are its source |

Licence texts: [`x265-GPL-2.0.txt`](third_party/licenses/x265-GPL-2.0.txt),
[`libheif-LGPL-3.0.txt`](third_party/licenses/libheif-LGPL-3.0.txt) and
[`libde265-LGPL-3.0.txt`](third_party/licenses/libde265-LGPL-3.0.txt) (each with the GPL-3.0 that the
LGPL-3.0 builds on), [`gcc-runtime-library-exception-3.1.txt`](third_party/licenses/gcc-runtime-library-exception-3.1.txt)
with [`gcc-runtime-GPL-3.0.txt`](third_party/licenses/gcc-runtime-GPL-3.0.txt),
[`winpthreads-MIT.txt`](third_party/licenses/winpthreads-MIT.txt),
[`pillow-heif-BSD-3-Clause.txt`](third_party/licenses/pillow-heif-BSD-3-Clause.txt), and pystray's
`COPYING` and `COPYING.LGPL` in `vendor/runtime/Lib/site-packages/pystray-0.19.5.dist-info`.

## Python

| Component | Version | Licence | Text |
|---|---|---|---|
| Python | 3.14 (embeddable runtime in `vendor/runtime`) | PSF-2.0 | [`python-PSF.txt`](third_party/licenses/python-PSF.txt) (also `vendor/runtime/LICENSE.txt`) |
| Microsoft Visual C++ runtime | `vcruntime140.dll`, `vcruntime140_1.dll` | Microsoft Visual C++ Redistributable terms (shipped with Python) | |

Python packages in `vendor/runtime/Lib/site-packages` (each licence text is in the package's `.dist-info` folder):

| Package | Version | Licence | Folder |
|---|---|---|---|
| annotated-doc | 0.0.5 | MIT | `annotated_doc-0.0.5.dist-info` |
| annotated-types | 0.8.0 | MIT | `annotated_types-0.8.0.dist-info` |
| anyio | 4.15.1 | MIT | `anyio-4.15.1.dist-info` |
| bottle | 0.13.4 | MIT | `bottle-0.13.4.dist-info` |
| cffi | 2.1.1 | MIT-0 | `cffi-2.1.1.dist-info` |
| click | 8.5.0 | BSD-3-Clause | `click-8.5.0.dist-info` |
| clr_loader | 0.3.1 | MIT | `clr_loader-0.3.1.dist-info` |
| colorama | 0.4.6 | BSD | `colorama-0.4.6.dist-info` |
| fastapi | 0.141.1 | MIT | `fastapi-0.141.1.dist-info` |
| fonttools | 4.64.0 | MIT | `fonttools-4.64.0.dist-info` |
| h11 | 0.16.0 | MIT | `h11-0.16.0.dist-info` |
| keyboard | 0.13.5 | MIT | `keyboard-0.13.5.dist-info` |
| pillow | 12.3.0 | MIT-CMU | `pillow-12.3.0.dist-info` |
| pillow_heif | 1.8.1 | BSD-3-Clause | `pillow_heif-1.8.1.dist-info` |
| proxy_tools | 0.1.0 | MIT | `proxy_tools-0.1.0.dist-info` |
| pycparser | 3.0 | BSD-3-Clause | `pycparser-3.0.dist-info` |
| pydantic | 2.13.5 | MIT | `pydantic-2.13.5.dist-info` |
| pydantic_core | 2.46.5 | MIT | `pydantic_core-2.46.5.dist-info` |
| pypdf | 6.17.0 | BSD-3-Clause | `pypdf-6.17.0.dist-info` |
| pystray | 0.19.5 | LGPL-3.0 | `pystray-0.19.5.dist-info` |
| python-multipart | 0.0.32 | Apache-2.0 | `python_multipart-0.0.32.dist-info` |
| pythonnet | 3.1.0 | MIT | `pythonnet-3.1.0.dist-info` |
| pywebview | 6.2.1 | BSD-3-Clause | `pywebview-6.2.1.dist-info` |
| six | 1.17.0 | MIT | `six-1.17.0.dist-info` |
| starlette | 1.6.0 | BSD-3-Clause | `starlette-1.6.0.dist-info` |
| typing_extensions | 4.16.0 | PSF-2.0 | `typing_extensions-4.16.0.dist-info` |
| typing-inspection | 0.4.4 | MIT | `typing_inspection-0.4.4.dist-info` |
| uvicorn | 0.52.4 | BSD-3-Clause | `uvicorn-0.52.4.dist-info` |
| watchdog | 6.0.0 | Apache-2.0 | `watchdog-6.0.0.dist-info` |

## User interface (`frontend/dist`)

| Component | Version | Licence | Text |
|---|---|---|---|
| React, React DOM | 18.3.1 | MIT | [`react-MIT.txt`](third_party/licenses/ui/react-MIT.txt), [`react-dom-MIT.txt`](third_party/licenses/ui/react-dom-MIT.txt) |
| scheduler | 0.23.2 | MIT | [`scheduler-MIT.txt`](third_party/licenses/ui/scheduler-MIT.txt) |
| Lucide (lucide-react) | 0.460.0 | ISC | [`lucide-react-ISC.txt`](third_party/licenses/ui/lucide-react-ISC.txt) |
| marked | 12.0.2 | MIT | [`marked-MIT.txt`](third_party/licenses/ui/marked-MIT.txt) |
| Papa Parse | 5.7.0 | MIT | [`papaparse-MIT.txt`](third_party/licenses/ui/papaparse-MIT.txt) |
| Prism | 1.30.0 | MIT | [`prismjs-MIT.txt`](third_party/licenses/ui/prismjs-MIT.txt) |
| clsx | 2.1.1 | MIT | [`clsx-MIT.txt`](third_party/licenses/ui/clsx-MIT.txt) |
| tailwind-merge | 2.6.1 | MIT | [`tailwind-merge-MIT.txt`](third_party/licenses/ui/tailwind-merge-MIT.txt) |
| Tailwind CSS (generated styles) | 3.4.19 | MIT | [`tailwindcss-MIT.txt`](third_party/licenses/ui/tailwindcss-MIT.txt) |
| PDF.js (pdfjs-dist) | 6.3.289 | Apache-2.0 | [`pdfjs-Apache-2.0.txt`](third_party/licenses/ui/pdfjs-Apache-2.0.txt) |
| PDF.js data: character maps, fonts, colour profiles, image decoders | with PDF.js | their own licences | the `LICENSE*` files in `frontend/dist/pdfjs/cmaps`, `standard_fonts`, `iccs`, and `wasm` |
