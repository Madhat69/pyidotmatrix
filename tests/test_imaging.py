"""Tests for the adapt_image helper."""

from PIL import Image

from pyidotmatrix.imaging import ResizeMode, adapt_image


def test_returns_canvas_sized_rgb_bytes():
    img = Image.new("RGB", (10, 20), (255, 0, 0))
    data = adapt_image(img, 32)
    assert len(data) == 32 * 32 * 3


def test_exact_size_image_passthrough():
    img = Image.new("RGB", (32, 32), (1, 2, 3))
    data = adapt_image(img, 32, resize_mode=ResizeMode.STRETCH)
    assert data == bytes([1, 2, 3]) * (32 * 32)


def test_accepts_path(tmp_path):
    path = tmp_path / "square.png"
    Image.new("RGB", (32, 32), (9, 9, 9)).save(path)
    data = adapt_image(str(path), 32, resize_mode=ResizeMode.STRETCH)
    assert data == bytes([9, 9, 9]) * (32 * 32)


def test_rgba_input_flattened_on_background():
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))  # fully transparent
    data = adapt_image(img, 32, background_color=(5, 6, 7), resize_mode=ResizeMode.STRETCH)
    assert data[0:3] == bytes([5, 6, 7])  # background shows through
