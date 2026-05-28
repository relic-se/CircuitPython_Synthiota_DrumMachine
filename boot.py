# SPDX-FileCopyrightText: 2026 Cooper Dalrymple (@relic-se)
#
# SPDX-License-Identifier: GPLv3

import os
import storage
import usb_cdc
import usb_hid
import usb_midi

# Rename drive
storage.remount("/", readonly=False)
mnt = storage.getmount("/")
mnt.label = "SYNTHIOTA"

# Disable write protection and unnecessary usb features
storage.remount("/", readonly=False, disable_concurrent_write_protection=True)
usb_hid.disable()
usb_cdc.enable(console=True, data=False)

# Rename MIDI interface
usb_midi.enable()
usb_midi.set_names(
    streaming_interface_name="synthiota MIDI",
    audio_control_interface_name="synthiota Audio",
    in_jack_name="synthiota Drum Machine",
    out_jack_name="synthiota Drum Machine",
)

# Create samples directory if not found
try:
    os.stat("/samples")
except OSError:
    os.mkdir("/samples")
