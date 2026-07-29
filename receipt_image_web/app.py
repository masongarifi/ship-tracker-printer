import io
import logging
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from fleet_receipt.config import load_settings
from fleet_receipt.printers.epson_usb import PrinterError

from .image_processor import (
    DEFAULT_PRINTER_WIDTH,
    ImageOptions,
    ImageProcessingError,
    process_image,
    validate_extension,
)
from .printer_service import PrinterBusyError, PrinterService

LOGGER = logging.getLogger(__name__)


def create_app(printer_service=None, settings=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    app.config["PRINTER_SERVICE"] = printer_service or PrinterService()
    configured = settings if settings is not None else load_settings()
    app.config["PRINTER_PIXEL_WIDTH"] = int(
        configured.get("printer_pixel_width", DEFAULT_PRINTER_WIDTH)
    )

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/preview")
    def preview():
        try:
            with _processed_upload(app) as processed:
                output = io.BytesIO()
                processed.save(output, "PNG")
                output.seek(0)
                return send_file(output, mimetype="image/png", max_age=0)
        except (ImageProcessingError, ValueError) as exc:
            return _error(str(exc), 400)
        except Exception:
            LOGGER.exception("Image preview failed")
            return _error("Image processing failure.", 500)

    @app.post("/print")
    def print_route():
        try:
            copies = _bounded_int("copies", 1, 1, 10)
            feed_lines = _bounded_int("feed_lines", 4, 0, 20)
            cut = _boolean("cut", True)
            with _processed_upload(app) as processed:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temporary:
                    processed.save(temporary, "PNG")
                    processed_path = Path(temporary.name)
                try:
                    warnings = app.config["PRINTER_SERVICE"].print_image(
                        processed_path, copies, feed_lines, cut
                    )
                finally:
                    processed_path.unlink(missing_ok=True)
            message = f"Printed {copies} cop{'y' if copies == 1 else 'ies'} successfully."
            if warnings:
                return jsonify(ok=True, message=message, warning=" ".join(warnings))
            return jsonify(ok=True, message=message)
        except (ImageProcessingError, ValueError) as exc:
            return _error(str(exc), 400)
        except PrinterBusyError as exc:
            return _error(str(exc), 409)
        except PrinterError as exc:
            LOGGER.exception("Printer failure")
            status = 503 if "not found" in str(exc).casefold() else 500
            return _error(str(exc), status)
        except Exception:
            LOGGER.exception("Unexpected print failure")
            return _error("Print failure. Check the service logs for details.", 500)

    @app.get("/health")
    def health():
        available, detail = app.config["PRINTER_SERVICE"].available()
        return jsonify(
            status="ok",
            service_running=True,
            printer_available=available,
            printer_detail=detail,
        )

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_exc):
        return _error("File too large. Maximum upload size is 20 MB.", 413)

    return app


class _processed_upload:
    def __init__(self, app):
        self.app = app
        self.path = None
        self.image = None

    def __enter__(self):
        upload = request.files.get("image")
        if upload is None or not upload.filename:
            raise ImageProcessingError("No file selected.")
        safe_name = secure_filename(upload.filename)
        validate_extension(safe_name)
        suffix = Path(safe_name).suffix.casefold()
        handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        self.path = Path(handle.name)
        try:
            upload.save(handle)
        finally:
            handle.close()
        try:
            self.image = process_image(
                self.path,
                _options(),
                self.app.config["PRINTER_PIXEL_WIDTH"],
            )
        except Exception:
            self.path.unlink(missing_ok=True)
            raise
        return self.image

    def __exit__(self, *_args):
        if self.image:
            self.image.close()
        if self.path:
            self.path.unlink(missing_ok=True)


def _options():
    rotation = request.form.get("rotation", "0")
    return ImageOptions(
        fit_mode=request.form.get("fit_mode", "fit"),
        dither=_boolean("dither", True),
        contrast=float(request.form.get("contrast", "1.15")),
        invert=_boolean("invert", False),
        rotation=int(rotation),
    )


def _boolean(name, default):
    value = request.form.get(name)
    if value is None:
        return default
    return value.casefold() in {"1", "true", "yes", "on"}


def _bounded_int(name, default, minimum, maximum):
    value = int(request.form.get(name, default))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name.replace('_', ' ').title()} must be between {minimum} and {maximum}.")
    return value


def _error(message, status):
    return jsonify(ok=False, error=message), status


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000)
