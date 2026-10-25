# Source code of the GPL and LGPL components

These archives are the complete source code of the GPL and LGPL binaries in Peek & Grep Portable
(see `THIRD_PARTY_NOTICES.md` at the top of the repository), as they were built:

| Archive | What it is |
|---|---|
| `x265-4.3.tar.gz` | x265 4.3 (https://github.com/Multicorewareinc/x265, tag 4.3, commit e9b88125dc21393b3fd8d68e98083bdfb89778a8). Built by MSYS2 as `mingw-w64-x265` 4.3-1 |
| `libde265-1.1.3.tar.gz` | libde265 1.1.3 (https://github.com/strukturag/libde265, tag v1.1.3, commit ba62bf4cfb3242f3bf0a45617ff09e35236e4d82). Built by MSYS2 as `mingw-w64-libde265` 1.1.3-1 |
| `libheif-1.23.6.tar.gz` | libheif 1.23.6 (https://github.com/strukturag/libheif, tag v1.23.6, commit f81f28ac014b1c28dee483ac45b72c6b05bc421a) |
| `pillow_heif-1.8.1-src.tar.gz` | pillow-heif 1.8.1, the source release from PyPI without its test images. Its `libheif/windows/mingw-w64-libheif/PKGBUILD` built the libheif DLL; `pillow_heif/_pillow_heif.c` is the extension module |
| `msys2-build-scripts-x265-4.3-1_libde265-1.1.3-1.tar.gz` | The MSYS2 build scripts (`PKGBUILD`, and x265's `0001-missing-include.patch`) that built the x265 and libde265 DLLs (https://github.com/msys2/MINGW-packages, commit 7b83aed2e5042206403eaa81bcefb12e86676aab) |

The Windows wheel `pillow_heif-1.8.1-cp314-cp314-win_amd64.whl` (PyPI, 11 October 2026) was built
with these sources by pillow-heif's release workflow (cibuildwheel and delvewheel on Windows,
MSYS2 MinGW-w64 toolchain). Its files are installed unchanged in `vendor/runtime/Lib/site-packages`.
