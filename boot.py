# SPDX-FileCopyrightText: 2026 Cooper Dalrymple (@relic-se)
#
# SPDX-License-Identifier: GPLv3

import os
import storage
import usb_hid
import usb_cdc

# Rename drive
storage.remount("/", readonly=False)
mnt = storage.getmount("/")
mnt.label = "SYNTHIOTA"

# Disable write protection and unnecessary usb features
storage.remount("/", readonly=False, disable_concurrent_write_protection=True)
usb_hid.disable()
usb_cdc.enable(console=True, data=False)

# Create samples directory if not found
try:
    os.stat("/samples")
except OSError:
    os.mkdir("/samples")
