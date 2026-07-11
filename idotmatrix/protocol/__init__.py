"""Pure packet builders for the iDotMatrix BLE protocol.

Every function here turns arguments into bytes with no I/O and no state, so the
device wire format is testable in isolation (see tests/). The transport layer
sends whatever these produce.

Full device feature parity: image (DIY frames), graffiti, common, chronograph,
countdown, clock, scoreboard, eco, fullscreen_color, effect, music_sync, text, gif.
text and gif depend on Pillow; the rest are pure byte layouts.

TODO: Alarm & Buzzer and MusicSync audio streaming are unimplemented in the
source project (not yet reverse-engineered).
"""
