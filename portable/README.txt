PEEK & GREP PORTABLE 3.0
========================

Peek & Grep finds files by name and by the text inside them, and shows a Quick Look
preview. It reads only the working folders that you choose.

START
-----
1. Double-click PeekGrep.exe.
2. On the first start, choose your working folders. Nothing is scanned before you confirm.
3. Search. Push Alt+Space at any time to show or hide the window.

KEYS
----
Up / Down       Move in the results
Space           Quick Look preview (Up / Down to go to the next file)
Enter           Open the file
Ctrl+Enter      Show the file in Explorer
Ctrl+C          Copy the file path
Ctrl+1 to 5     Filter: All, Code, Docs, Data, Media
Backspace       In an empty search field: leave the folder scope
Esc             Close the preview, clear the search, then hide the window

PORTABLE
--------
- No installation. Everything stays in this folder:
    runtime\   Python runtime (only what the app needs)
    app\       the program
    data\      your settings, the index, the log, and the window cache
    third_party\  licences of the bundled software, and the source of its GPL parts
- The app writes nothing to the registry and nothing to the Startup folder. Only if you turn
  on "Start with Windows" (Settings, or the tray menu) it adds one value for your user under
  HKCU\Software\Microsoft\Windows\CurrentVersion\Run. Turning it off removes it again.
- To move the app, move the complete folder (and PeekGrep.exe, if it is next to it).
- If the folder is on a USB drive that gets another drive letter, folders on that drive
  are moved to the new letter automatically.
- To reset, quit the app and delete the data folder.

PHOTOS AND VIDEOS
-----------------
Quick Look shows iPhone photos (HEIC), videos (MP4, MOV, WebM), and Snapchat files, also
files without an extension. Videos in HEVC (the iPhone's "High Efficiency" format) play
when Windows has the HEVC decoder ("HEVC Video Extensions" in the Microsoft Store).

LICENCE
-------
Peek & Grep Portable is licensed under the MIT License (LICENSE.txt). It covers the app's own code;
the bundled third-party software keeps its own licences (below).

THIRD-PARTY SOFTWARE
--------------------
The app contains open-source software by others (Python, the user interface libraries,
PDF.js, and libheif with x265 for HEIC photos). See THIRD_PARTY_NOTICES.md and the
third_party folder: the licences, and the complete source code of the GPL and LGPL parts.

REQUIREMENTS
------------
Windows 10 or 11, 64-bit, with the Microsoft Edge WebView2 Runtime (included in Windows 11).

QUIT
----
The X button hides the window to the tray. To quit, use the ... menu in the window,
or right-click the tray icon and select "Quit Peek & Grep".
