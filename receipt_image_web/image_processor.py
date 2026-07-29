from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError

SUPPORTED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
DEFAULT_PRINTER_WIDTH = 576


class ImageProcessingError(ValueError):
    pass


@dataclass(frozen=True)
class ImageOptions:
    fit_mode: str = "fit"
    dither: bool = True
    contrast: float = 1.15
    invert: bool = False
    rotation: int = 0


def validate_extension(filename: str) -> None:
    extension = Path(filename).suffix.lstrip(".").casefold()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ImageProcessingError("Unsupported format. Choose PNG, JPG, JPEG, or WEBP.")


def process_image(
    source: str | Path,
    options: ImageOptions,
    printer_width: int = DEFAULT_PRINTER_WIDTH,
) -> Image.Image:
    if printer_width <= 0:
        raise ImageProcessingError("Printer pixel width must be positive.")
    if options.fit_mode not in {"fit", "original", "crop"}:
        raise ImageProcessingError("Invalid fit mode.")
    if options.rotation not in {-90, 0, 90}:
        raise ImageProcessingError("Invalid rotation.")
    try:
        with Image.open(source) as opened:
            opened.verify()
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("L")
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageProcessingError("The uploaded file is corrupted or is not a valid image.") from exc

    if options.rotation:
        image = image.rotate(options.rotation, expand=True)
    image = _resize(image, printer_width, options.fit_mode)
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image).enhance(max(0.1, min(options.contrast, 3.0)))
    if options.invert:
        image = ImageOps.invert(image)
    dither = Image.Dither.FLOYDSTEINBERG if options.dither else Image.Dither.NONE
    return image.convert("1", dither=dither)


def _resize(image: Image.Image, width: int, mode: str) -> Image.Image:
    if mode == "original":
        if image.width <= width:
            return image
        scale = width / image.width
    elif mode == "crop":
        if image.width > width:
            left = (image.width - width) // 2
            return image.crop((left, 0, left + width, image.height))
        scale = width / image.width
    else:
        scale = min(1.0, width / image.width)
    height = max(1, round(image.height * scale))
    output_width = width if mode != "original" or image.width > width else image.width
    return image.resize((output_width, height), Image.Resampling.LANCZOS)
