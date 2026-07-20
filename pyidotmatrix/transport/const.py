"""BLE identifiers for iDotMatrix devices (from the device's GATT table)."""

# Characteristic we write commands to.
UUID_WRITE = "0000fa02-0000-1000-8000-00805f9b34fb"

# Characteristic the device notifies on. Notify-only: it cannot be read, so we
# never issue a GATT read against it (strict stacks reject it — see transport).
UUID_NOTIFY = "0000fa03-0000-1000-8000-00805f9b34fb"

# Advertised names of iDotMatrix devices start with this prefix.
DEVICE_NAME_PREFIX = "IDM-"
