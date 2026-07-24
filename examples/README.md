# Examples

Runnable, single-purpose scripts that exercise the `pyidotmatrix` SDK against
either real hardware or the built-in simulator. Each script has a module
docstring stating what it demonstrates and what hardware it needs, and takes
the device's MAC address from `argv[1]` (falling back to `discover()` when
omitted) so you can point any of them at your own panel without editing code.
Scripts that need a real panel assume a 32×32 screen; adjust `ScreenSize` if
yours differs. None of these are exercised in CI — they're meant to be read
and run by hand against a device.

| Script | Shows | Hardware |
|---|---|---|
| [01_discover_and_clock.py](01_discover_and_clock.py) | `discover()`, `connect_to()`, the native clock face | a panel |
| [02_show_image.py](02_show_image.py) | `show_image()` and the `adapt_image` + `show_frame` it wraps | a panel + an image file |
| [03_full_frame_animation.py](03_full_frame_animation.py) | hand-built RGB frames via `show_frame`, paced to the ~1.75 fps device render cap | a panel |
| [04_graffiti_pixels.py](04_graffiti_pixels.py) | delta pixel updates and the h/v mirror `move_type` | a panel |
| [05_gif_upload.py](05_gif_upload.py) | GIF upload, `UploadError` handling, `activate_stored()`'s ~1s instant re-show | a panel + a GIF file |
| [06_native_widgets.py](06_native_widgets.py) | countdown, chronograph (stopwatch), scoreboard, and scrolling text | a panel (+ a TTF font for the text step) |
| [07_simulator.py](07_simulator.py) | `SimulatorDisplay`, printing frames as ASCII art | none |
| [08_capability_table.py](08_capability_table.py) | iterating `CAPABILITIES` and guarding a call on `KNOWN_BROKEN` before sending it | none |

See [docs/getting-started.md](../docs/getting-started.md) for the narrative
walkthrough these scripts assume, and
[docs/hardware-compatibility.md](../docs/hardware-compatibility.md) for what
every capability status in `08_capability_table.py` actually means.
