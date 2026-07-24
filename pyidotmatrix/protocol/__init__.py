"""Pure packet builders for the iDotMatrix BLE protocol.

Every function here turns arguments into bytes with no I/O and no state, so the
device wire format is testable in isolation (see tests/). The transport layer
sends whatever these produce.

Full device feature parity: image (DIY frames), graffiti, common, chronograph,
countdown, clock, scoreboard, eco, fullscreen_color, effect, music_sync, text, gif,
timer, schedule. text and gif depend on Pillow; the rest are pure byte layouts.

Alarm & Buzzer (Timer + Weekly Schedule) IS implemented -- see protocol.timer /
protocol.schedule, exposed as client.experimental.timer_set / timer_close /
schedule_set_theme / schedule_master_switch, and hardware-verified (see
pyidotmatrix.capabilities for the evidence table).

TODO: MusicSync audio streaming (the mic-input pipeline, as opposed to the
already-ported set_mic_type/send_image_rhythm/stop_rhythm control commands) is
unimplemented -- not yet reverse-engineered.
"""
