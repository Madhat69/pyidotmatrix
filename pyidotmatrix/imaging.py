"""Image fitting helpers used when adapting media (GIFs) to the device canvas.

This is the one place the driver touches image scaling, and only because the
device's GIF feature needs canvas-sized frames. The DIY frame path does NOT use
this — show_frame takes finished, exact-size RGB from the caller.
"""

from enum import Enum
from os import PathLike

from PIL import Image, ImageOps


class ResizeMode(Enum):
    FIT = "fit"        # keep aspect ratio, letterbox with background
    FILL = "fill"      # keep aspect ratio, crop overflow
    STRETCH = "stretch"  # ignore aspect ratio


def adapt_image(
    image: Image.Image | str | PathLike,
    canvas_size: int,
    resize_mode: ResizeMode = ResizeMode.FIT,
    background_color: tuple[int, int, int] = (0, 0, 0),
    do_palettize: bool = False,
) -> bytes:
    """Fits an image (or image path) to the canvas and returns RGB bytes.

    Pure helper for the DIY frame path: the result is ready for
    DisplayBackend.show_frame. Palettizing suits pixel art (uses nearest-neighbour
    resampling); leave it off for photos.
    """
    if isinstance(image, Image.Image):
        opened = None
        source = image
    else:
        opened = Image.open(image)
        source = opened
    try:
        fitted = ImageOps.exif_transpose(source)
        resample = Image.Resampling.NEAREST if do_palettize else Image.Resampling.LANCZOS
        fitted = resize_to_canvas(fitted, canvas_size, resize_mode, resample, background_color, mode="RGB")
        if do_palettize:
            fitted = palettize(fitted)
        if fitted.mode != "RGB":
            fitted = fitted.convert("RGB")
        return fitted.tobytes()
    finally:
        if opened is not None:
            opened.close()


def palettize(image: Image.Image, colors: int = 256) -> Image.Image:
    """Converts to an adaptive palette. Good for pixel art, bad for photos."""
    return image.convert(mode="P", dither=Image.Dither.NONE, palette=Image.Palette.ADAPTIVE, colors=colors)


def resize_to_canvas(
    image: Image.Image,
    canvas_size: int,
    resize_mode: ResizeMode,
    resample: Image.Resampling,
    background_color: tuple[int, int, int] = (0, 0, 0),
    mode: str = "RGB",
) -> Image.Image:
    """Resizes image to a square canvas_size x canvas_size, centered on background."""
    if resize_mode == ResizeMode.FIT:
        ratio = min(canvas_size / image.width, canvas_size / image.height)
        image = image.resize((int(image.width * ratio), int(image.height * ratio)), resample)
    elif resize_mode == ResizeMode.FILL:
        ratio = max(canvas_size / image.width, canvas_size / image.height)
        image = image.resize((int(image.width * ratio), int(image.height * ratio)), resample)
        left = (image.width - canvas_size) // 2
        top = (image.height - canvas_size) // 2
        image = image.crop((left, top, left + canvas_size, top + canvas_size))
    elif resize_mode == ResizeMode.STRETCH:
        image = image.resize((canvas_size, canvas_size), resample)

    # Composite onto a background so transparent areas and letterboxing are filled.
    with_alpha = Image.new("RGBA", (canvas_size, canvas_size), background_color)
    offset = ((canvas_size - image.width) // 2, (canvas_size - image.height) // 2)
    with_alpha.paste(image, offset, mask=image.convert("RGBA"))

    canvas = Image.new(mode, (canvas_size, canvas_size), background_color)
    canvas.paste(with_alpha, ((canvas_size - with_alpha.width) // 2, (canvas_size - with_alpha.height) // 2))
    return canvas
