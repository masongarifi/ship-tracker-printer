import io
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from receipt_image_web.app import create_app
from receipt_image_web.image_processor import ImageOptions, ImageProcessingError, process_image
from receipt_image_web.printer_service import PrinterBusyError, PrinterService


def image_bytes(fmt="PNG", size=(1200, 600)):
    stream = io.BytesIO()
    Image.new("RGB", size, "white").save(stream, fmt)
    stream.seek(0)
    return stream


def test_processing_validates_contents_and_preserves_aspect_ratio(tmp_path):
    source = tmp_path / "wide.png"
    source.write_bytes(image_bytes().read())
    result = process_image(source, ImageOptions(), printer_width=576)
    assert result.mode == "1"
    assert result.size == (576, 288)

    source.write_text("not an image", encoding="utf-8")
    with pytest.raises(ImageProcessingError, match="not a valid image"):
        process_image(source, ImageOptions())


def test_crop_mode_center_crops_without_stretching(tmp_path):
    source = tmp_path / "wide.png"
    source.write_bytes(image_bytes(size=(800, 300)).read())
    result = process_image(
        source, ImageOptions(fit_mode="crop"), printer_width=576
    )
    assert result.size == (576, 300)


class RecordingService:
    def __init__(self):
        self.paths = []

    def available(self):
        return True, None

    def print_image(self, path, copies, feed_lines, cut):
        path = Path(path)
        assert path.exists()
        self.paths.append((path, copies, feed_lines, cut))
        return []


def test_preview_print_and_temporary_files_are_deleted():
    service = RecordingService()
    app = create_app(printer_service=service, settings={})
    client = app.test_client()
    response = client.post(
        "/preview",
        data={"image": (image_bytes(), "photo.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.mimetype == "image/png"

    response = client.post(
        "/print",
        data={
            "image": (image_bytes(), "photo.png"),
            "copies": "2",
            "feed_lines": "4",
            "cut": "true",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    path, copies, feed, cut = service.paths[0]
    assert (copies, feed, cut) == (2, 4, True)
    assert not path.exists()


def test_rejects_bad_extension_and_bad_image():
    app = create_app(printer_service=RecordingService(), settings={})
    client = app.test_client()
    response = client.post(
        "/preview",
        data={"image": (io.BytesIO(b"hello"), "photo.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    response = client.post(
        "/preview",
        data={"image": (io.BytesIO(b"hello"), "photo.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


class BlockingPrinter:
    def check_available(self):
        pass

    def print_image(self, *_args, **_kwargs):
        time.sleep(0.1)


def test_concurrent_jobs_are_blocked():
    service = PrinterService()
    service._printer = BlockingPrinter()
    first = threading.Thread(target=service.print_image, args=("x", 1, 4, True))
    first.start()
    time.sleep(0.02)
    with pytest.raises(PrinterBusyError):
        service.print_image("x", 1, 4, True)
    first.join()


def test_health_reports_printer_status():
    app = create_app(printer_service=RecordingService(), settings={})
    body = app.test_client().get("/health").get_json()
    assert body["service_running"] is True
    assert body["printer_available"] is True
