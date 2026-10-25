"""Photos and videos from phones and Snapchat (app/media.py).

tests/fixtures/media (made with Pillow, pillow-heif, and ffmpeg, a few KB each):
    IMG_0001.heic             iPhone-like photo: stored 96x64, EXIF orientation 6 (shown 64x96), Apple iPhone 15 Pro
    IMG_0002.MOV              H.264 + AAC, rotated 90 degrees (shown 64x96), Apple keys (make, model, creation date)
    IMG_0003.MOV              HEVC ("hvc1", the iPhone's default), no sound
    2024-06-01_abc-main.mp4   Snapchat memory, with its text in 2024-06-01_abc-overlay.png
    snap_noext                a JPEG without extension (Snapchat export)
    snap_video_noext          a WebM video without extension
"""

import io
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.media import image_info, media_extension, preview_jpeg, snapchat_overlay, sniff, video_info

MEDIA = Path(__file__).parent / "fixtures" / "media"


def test_type_from_content():
    assert sniff(str(MEDIA / "IMG_0001.heic")) == ".heic"
    assert sniff(str(MEDIA / "IMG_0002.MOV")) == ".mov"
    assert sniff(str(MEDIA / "2024-06-01_abc-main.mp4")) == ".mp4"
    assert media_extension(str(MEDIA / "snap_noext"), "") == ".jpg"
    assert media_extension(str(MEDIA / "snap_video_noext"), "") == ".webm"
    # Other files keep their extension (no reading for text files)
    assert media_extension(str(MEDIA / "IMG_0001.heic"), ".txt") == ".txt"


def test_heic_photo():
    info = image_info(str(MEDIA / "IMG_0001.heic"))
    assert (info["width"], info["height"]) == (64, 96)
    assert info["camera"] == "Apple iPhone 15 Pro" and info["taken"] == "2024-05-01 14:03"
    # Turned upright: the yellow corner (top left as stored) is top right after orientation 6
    jpeg = Image.open(io.BytesIO(preview_jpeg(str(MEDIA / "IMG_0001.heic"))))
    assert jpeg.format == "JPEG" and jpeg.size == (64, 96)
    r, g, b = jpeg.getpixel((jpeg.size[0] - 3, 2))
    assert r > 200 and g > 150 and b < 80


def test_videos():
    mov = video_info(str(MEDIA / "IMG_0002.MOV"))
    assert mov["codec_name"] == "H.264" and mov["audio"] and mov["duration"] == 1.0
    assert (mov["width"], mov["height"]) == (64, 96) and mov["rotation"] in (90, 270)
    assert mov["camera"] == "Apple iPhone 15 Pro" and mov["created"] == "2024-05-02 12:20"
    hevc = video_info(str(MEDIA / "IMG_0003.MOV"))
    assert hevc["codec"] == "hvc1" and hevc["codec_name"] == "HEVC (H.265)" and not hevc["audio"]
    assert video_info(str(MEDIA / "snap_noext")) is None  # not a video


def test_snapchat_overlay():
    assert snapchat_overlay(str(MEDIA / "2024-06-01_abc-main.mp4")) == str(MEDIA / "2024-06-01_abc-overlay.png")
    assert snapchat_overlay(str(MEDIA / "IMG_0002.MOV")) is None


def test_preview_api(tmp_path):
    from app.main import app
    from app.state import settings_store

    for f in MEDIA.iterdir():
        shutil.copy(f, tmp_path / f.name)
    settings_store.set_folders([str(tmp_path)])
    client = TestClient(app)

    def preview(name):
        res = client.get("/api/preview", params={"path": str(tmp_path / name)})
        assert res.status_code == 200, res.text
        return res.json()

    heic = preview("IMG_0001.heic")
    assert heic["preview_type"] == "image" and heic["image_meta"]["camera"] == "Apple iPhone 15 Pro"
    shown = client.get(heic["display_url"])
    assert shown.status_code == 200 and shown.headers["content-type"] == "image/jpeg"
    assert preview("snap_noext")["preview_type"] == "image" and preview("snap_noext")["display_url"] is None

    mov = preview("IMG_0002.MOV")
    assert mov["preview_type"] == "video" and mov["video_meta"]["codec"] == "avc1"
    raw = client.get(mov["raw_url"], headers={"Range": "bytes=0-99"})
    assert raw.status_code == 206 and raw.headers["content-type"] == "video/mp4" and len(raw.content) == 100

    memory = preview("2024-06-01_abc-main.mp4")
    assert memory["preview_type"] == "video" and "abc-overlay.png" in memory["overlay_url"]
    webm = preview("snap_video_noext")
    assert webm["preview_type"] == "video"
    assert client.get(webm["raw_url"]).headers["content-type"] == "video/webm"


def test_categories_and_crawl(tmp_path):
    from app.indexer.crawler import build_file_record
    from app.indexer.parsers import get_file_category

    for ext in (".heic", ".HEIC", ".mov", ".mp4", ".webm", ".jpg"):
        assert get_file_category(ext) == "media"
    shutil.copy(MEDIA / "snap_noext", tmp_path / "snap_noext")
    (tmp_path / "notes").write_text("plain words")
    assert build_file_record(str(tmp_path / "snap_noext"))["category"] == "media"
    assert build_file_record(str(tmp_path / "notes"))["category"] == "plain"


def test_svg_stays_an_image(tmp_path):
    from app.main import app
    from app.state import settings_store

    (tmp_path / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
    settings_store.set_folders([str(tmp_path)])
    res = TestClient(app).get("/api/preview", params={"path": str(tmp_path / "logo.svg")}).json()
    assert res["preview_type"] == "image" and res["image_meta"] is None
