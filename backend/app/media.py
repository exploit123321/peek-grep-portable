"""Photos and videos: phones (iPhone .heic and .mov) and Snapchat (memories and saved snaps).

- The type of a file comes from its first bytes when the extension is missing or wrong
  (Snapchat exports, HEIC photos saved as .jpg).
- HEIC/HEIF (and TIFF) are turned into JPEG for the preview: WebView2 cannot show them.
- MP4/MOV are read for duration, size, rotation, codec, and the phone's make, model, and date.
- A Snapchat memory "...-main.jpg" or "...-main.mp4" has its text and stickers in "...-overlay.png".
"""

import io
import os
import struct
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageOps

try:  # HEIC and HEIF photos (pillow-heif: libheif with the libde265 decoder)
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_AVAILABLE = True
except Exception:  # pragma: no cover - the app still runs, HEIC shows as a file without preview
    HEIF_AVAILABLE = False

# Images the WebView shows itself
BROWSER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".jfif", ".gif", ".svg", ".webp", ".bmp", ".ico", ".avif"}
# Images that are turned into JPEG for the preview
CONVERT_IMAGE_EXTENSIONS = {".heic", ".heif", ".hif", ".tif", ".tiff"}
IMAGE_EXTENSIONS = BROWSER_IMAGE_EXTENSIONS | CONVERT_IMAGE_EXTENSIONS
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".3gp", ".3g2", ".mkv", ".avi", ".wmv", ".mpg", ".mpeg",
                    ".mts", ".m2ts", ".qt"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

# The type the browser gets for a video (".mov" as MP4: same container family, and what WebView2 plays)
VIDEO_MIME = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/mp4", ".qt": "video/mp4",
    ".3gp": "video/3gpp", ".3g2": "video/3gpp2", ".webm": "video/webm", ".mkv": "video/webm",
}

PREVIEW_MAX_SIDE = 2560


# -- the type from the first bytes --------------------------------------------------

_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1"}
_3GP_BRANDS = {b"3gp4", b"3gp5", b"3gp6", b"3gg6", b"3g2a", b"3g2b"}


def sniff(path: str) -> Optional[str]:
    """The extension that the content has (".jpg", ".heic", ".mov", ...), or None."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return None
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return ".webm" if b"webm" in head else ".mkv"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        compatible = head[16:64]
        if brand in (b"avif", b"avis") or (brand in (b"mif1", b"msf1") and b"avif" in compatible):
            return ".avif"
        if brand in _HEIF_BRANDS:
            return ".heic"
        if brand == b"qt  ":
            return ".mov"
        if brand in _3GP_BRANDS:
            return ".3gp"
        return ".mp4"
    return None


def media_extension(path: str, ext: str) -> str:
    """The extension to treat a file as: its content decides for media (a HEIC photo named .jpg,
    a Snapchat file without extension); other files keep theirs."""
    found = sniff(path) if (ext in MEDIA_EXTENSIONS or ext in ("", ".unknown", ".media", ".bin", ".dat")) else None
    return found or ext


# -- photos ------------------------------------------------------------------------

_EXIF_IFD = 0x8769
_MAKE, _MODEL, _DATETIME, _ORIENTATION = 0x010F, 0x0110, 0x0132, 0x0112
_DATETIME_ORIGINAL = 0x9003


def _exif_date(text: Any) -> Optional[str]:
    """ "2024:05:01 14:03:22" -> "2024-05-01 14:03"."""
    if not isinstance(text, str) or len(text) < 16:
        return None
    try:
        return datetime.strptime(text[:19], "%Y:%m:%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _camera(make: Any, model: Any) -> Optional[str]:
    make = make.strip("\x00 ") if isinstance(make, str) else ""
    model = model.strip("\x00 ") if isinstance(model, str) else ""
    if model and make and model.lower().startswith(make.lower()):
        return model  # "Apple" + "iPhone 15 Pro" stays "Apple iPhone 15 Pro"; "Canon" + "Canon EOS R5" not twice
    return " ".join(p for p in (make, model) if p) or None


def image_info(path: str) -> Optional[Dict[str, Any]]:
    """Size as shown (after the EXIF rotation), format, and the photo's date and camera."""
    try:
        with Image.open(path) as img:
            width, height = img.size
            exif = img.getexif()
            orientation = exif.get(_ORIENTATION, 1)
            if orientation in (5, 6, 7, 8):
                width, height = height, width
            sub = exif.get_ifd(_EXIF_IFD) if exif else {}
            return {
                "width": width,
                "height": height,
                "format": (img.format or os.path.splitext(path)[1].lstrip(".")).upper(),
                "mode": img.mode,
                "aspect_ratio": _aspect(width, height),
                "taken": _exif_date(sub.get(_DATETIME_ORIGINAL)) or _exif_date(exif.get(_DATETIME)),
                "camera": _camera(exif.get(_MAKE), exif.get(_MODEL)),
            }
    except Exception:
        return None


def _aspect(width: int, height: int) -> str:
    from math import gcd
    if not width or not height:
        return ""
    g = gcd(width, height)
    return f"{width // g}:{height // g}"


_jpeg_cache: "OrderedDict[Tuple[str, int, int, int], bytes]" = OrderedDict()
_jpeg_lock = threading.Lock()
_JPEG_CACHE_ENTRIES = 12


def preview_jpeg(path: str, max_side: int = PREVIEW_MAX_SIDE) -> bytes:
    """The photo as JPEG for the preview: turned upright, at most max_side pixels long. The last
    few are kept, so going back and forth between photos is instant."""
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size, max_side)
    with _jpeg_lock:
        hit = _jpeg_cache.get(key)
        if hit is not None:
            _jpeg_cache.move_to_end(key)
            return hit
    with Image.open(path) as img:
        img.draft("RGB", (max_side, max_side))  # JPEG: decode at a smaller size at once
        img = ImageOps.exif_transpose(img)
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        if img.mode not in ("RGB", "L"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
    data = buf.getvalue()
    with _jpeg_lock:
        _jpeg_cache[key] = data
        while len(_jpeg_cache) > _JPEG_CACHE_ENTRIES:
            _jpeg_cache.popitem(last=False)
    return data


# -- videos (MP4, MOV, 3GP: ISO base media boxes) -----------------------------------

_MAC_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)
MAX_MOOV_BYTES = 64 * 1024 * 1024

CODEC_NAMES = {
    "avc1": "H.264", "avc3": "H.264", "hvc1": "HEVC (H.265)", "hev1": "HEVC (H.265)",
    "dvh1": "Dolby Vision (HEVC)", "dvhe": "Dolby Vision (HEVC)", "av01": "AV1", "vp09": "VP9", "vp08": "VP8",
    "mp4v": "MPEG-4", "jpeg": "Motion JPEG", "mjpa": "Motion JPEG", "s263": "H.263", "h263": "H.263",
    "apch": "ProRes 422 HQ", "apcn": "ProRes 422", "apcs": "ProRes 422 LT", "apco": "ProRes 422 Proxy",
    "ap4h": "ProRes 4444", "ap4x": "ProRes 4444 XQ", "aprn": "ProRes RAW", "aprh": "ProRes RAW HQ",
}


def _boxes(data: bytes, start: int = 0, end: Optional[int] = None):
    """(type, content start, content end) of the boxes in data[start:end]."""
    end = len(data) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, pos)
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind.decode("latin-1"), pos + header, pos + size
        pos += size


def _child(data: bytes, start: int, end: int, *path: str) -> Optional[Tuple[int, int]]:
    for name in path:
        for kind, a, b in _boxes(data, start, end):
            if kind == name:
                start, end = a, b
                break
        else:
            return None
    return start, end


def _read_moov(path: str) -> Optional[bytes]:
    """The "moov" box (the index of the file), wherever it is (iPhone: often at the end)."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        total = f.tell()
        pos = 0
        while pos + 8 <= total:
            f.seek(pos)
            head = f.read(16)
            if len(head) < 8:
                return None
            size, kind = struct.unpack_from(">I4s", head)
            header = 8
            if size == 1 and len(head) >= 16:
                size, header = struct.unpack_from(">Q", head, 8)[0], 16
            elif size == 0:
                size = total - pos
            if size < header:
                return None
            if kind == b"moov":
                if size > MAX_MOOV_BYTES:
                    return None
                f.seek(pos + header)
                return f.read(size - header)
            pos += size
    return None


def _mac_time(seconds: int) -> Optional[str]:
    if seconds <= 0:
        return None
    try:
        return (_MAC_EPOCH + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M")
    except OverflowError:
        return None


def _apple_keys(moov: bytes) -> Dict[str, str]:
    """Phone metadata in "keys" and "ilst" (com.apple.quicktime.model, ...): in moov/meta (iPhone)
    or moov/udta/meta (other writers)."""
    found = _child(moov, 0, len(moov), "meta") or _child(moov, 0, len(moov), "udta", "meta")
    if not found:
        return {}
    a, b = found
    if moov[a + 4:a + 8] not in (b"hdlr", b"keys", b"ilst"):
        a += 4  # an ISO "meta" box has version and flags first; a QuickTime one does not
    keys: List[str] = []
    out: Dict[str, str] = {}
    for kind, s, e in _boxes(moov, a, b):
        if kind == "keys":
            count = struct.unpack_from(">I", moov, s + 4)[0]
            pos = s + 8
            for _ in range(count):
                size = struct.unpack_from(">I", moov, pos)[0]
                keys.append(moov[pos + 8:pos + size].decode("utf-8", "replace"))
                pos += size
        elif kind == "ilst":
            for item, s2, e2 in _boxes(moov, s, e):
                index = struct.unpack(">I", item.encode("latin-1"))[0]
                data = _child(moov, s2, e2, "data")
                if data and 1 <= index <= len(keys):
                    value = moov[data[0] + 8:data[1]]  # after the type and the locale
                    out[keys[index - 1]] = value.decode("utf-8", "replace").strip("\x00 ")
    return out


def _udta_text(moov: bytes, name: str) -> Optional[str]:
    """QuickTime user data like "©mod" (2 bytes length, 2 bytes language, text)."""
    found = _child(moov, 0, len(moov), "udta", name)
    if not found:
        return None
    a, b = found
    if b - a >= 4:
        length = struct.unpack_from(">H", moov, a)[0]
        text = moov[a + 4:a + 4 + length].decode("utf-8", "replace").strip("\x00 ")
        return text or None
    return None


def video_info(path: str) -> Optional[Dict[str, Any]]:
    """Duration (s), size as shown, rotation, video codec, has sound, date, and the phone."""
    try:
        moov = _read_moov(path)
    except OSError:
        return None
    if not moov:
        return None
    info: Dict[str, Any] = {"duration": None, "width": None, "height": None, "rotation": 0, "codec": None,
                            "codec_name": None, "audio": False, "created": None, "camera": None}
    mvhd = _child(moov, 0, len(moov), "mvhd")
    if mvhd:
        a = mvhd[0]
        if moov[a] == 1:
            created, _, timescale, duration = struct.unpack_from(">QQIQ", moov, a + 4)
        else:
            created, _, timescale, duration = struct.unpack_from(">IIII", moov, a + 4)
        if timescale:
            info["duration"] = round(duration / timescale, 2)
        info["created"] = _mac_time(created)
    for kind, a, b in _boxes(moov):
        if kind != "trak":
            continue
        hdlr = _child(moov, a, b, "mdia", "hdlr")
        handler = moov[hdlr[0] + 8:hdlr[0] + 12] if hdlr else b""
        if handler == b"soun":
            info["audio"] = True
        if handler != b"vide" or info["codec"]:
            continue
        stsd = _child(moov, a, b, "mdia", "minf", "stbl", "stsd")
        if stsd and stsd[1] - stsd[0] >= 16:
            codec = moov[stsd[0] + 12:stsd[0] + 16].decode("latin-1")
            info["codec"] = codec
            info["codec_name"] = CODEC_NAMES.get(codec, codec.strip())
        tkhd = _child(moov, a, b, "tkhd")
        if tkhd:
            t = tkhd[0]
            base = t + (4 + 32 if moov[t] == 1 else 4 + 20)  # past the times, track id, and duration
            matrix = struct.unpack_from(">9i", moov, base + 16)
            w, h = struct.unpack_from(">II", moov, base + 16 + 36)
            w, h = w >> 16, h >> 16
            from math import atan2, degrees
            rotation = round(degrees(atan2(matrix[1], matrix[0]))) % 360
            info["rotation"] = rotation
            info["width"], info["height"] = (h, w) if rotation in (90, 270) else (w, h)
    apple = _apple_keys(moov)
    make = apple.get("com.apple.quicktime.make") or _udta_text(moov, "\xa9mak")
    model = apple.get("com.apple.quicktime.model") or _udta_text(moov, "\xa9mod")
    info["camera"] = _camera(make, model)
    day = apple.get("com.apple.quicktime.creationdate") or _udta_text(moov, "\xa9day")
    if day and len(day) >= 16 and day[4] == "-":
        info["created"] = day[:10] + " " + day[11:16]  # the phone's local time
    return info


# -- Snapchat ----------------------------------------------------------------------

def snapchat_overlay(path: str) -> Optional[str]:
    """The overlay (text, stickers, drawings) of a Snapchat memory: "<name>-main.jpg/.mp4" has it
    in "<name>-overlay.png" (or .webp) next to it."""
    folder, name = os.path.split(path)
    stem = os.path.splitext(name)[0]
    if not stem.lower().endswith("-main"):
        return None
    base = stem[:-5]
    for ext in (".png", ".webp", ".PNG", ".WEBP", ".jpg"):
        candidate = os.path.join(folder, f"{base}-overlay{ext}")
        if os.path.isfile(candidate):
            return candidate
    return None
