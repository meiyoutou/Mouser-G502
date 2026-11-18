"""HID++ transaction tags and side-effect-free delayed-response polling.

Some receiver/device combinations release a queued reply only after another
radio request. Poll with IRoot.ping, never by repeating a configuration command.
Keep discovery, runtime and polling software IDs separate; software ID zero is
reserved for unsolicited device notifications.
"""

from itertools import cycle


DISCOVERY_SOFTWARE_IDS = (0x0D, 1, 3, 5, 7, 9, 0x0B)
RUNTIME_SOFTWARE_IDS = (0x0A, 0x0C, 0x0E, 2, 4, 6, 8)
POLL_SOFTWARE_ID = 0x0F
REPLY_POLL_INTERVAL = 0.18
MAX_REPLY_POLLS = 2
_discovery_ids = cycle(DISCOVERY_SOFTWARE_IDS)
_ping_nonces = cycle(range(1, 256))


def next_discovery_id():
    # Continue across probe instances: a reopened handle may see a late reply
    # from the scan that preceded binding.
    return next(_discovery_ids)


def next_ping_nonce():
    return next(_ping_nonces)


def reply_poll_packet(slot):
    return [0x11, slot, 0, 0x10 | POLL_SOFTWARE_ID, 0, 0, 0xA5] + [0] * 13
