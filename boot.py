# SPDX-FileCopyrightText: 2026 Cooper Dalrymple (@relic-se)
#
# SPDX-License-Identifier: GPLv3

import os
import storage
import supervisor
import usb_audio
import usb_cdc
import usb_hid
import usb_midi

STEREO = supervisor.get_setting("STEREO", False)
USB_AUDIO = supervisor.get_setting("USB_AUDIO", False)

# Rename device
supervisor.set_usb_identification(
    manufacturer='todbot',
    product='synthiota',
)

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

# Setup USB audio
if USB_AUDIO:
    usb_audio.enable(
        sample_rate=32000 if STEREO else 44100,
        channel_count=2 if STEREO else 1,
        microphone=True,
        speaker=False,
    )

# Create samples directory if not found
try:
    os.stat("/samples")
except OSError:
    os.mkdir("/samples")
