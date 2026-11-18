"""Reproduce the receiver that releases reply N only after request N+1."""

from collections import deque
import unittest
from unittest.mock import patch

from core import hid_gesture as h
from core import logi_discovery as discovery
from core.hidpp_transaction import (
    DISCOVERY_SOFTWARE_IDS, MAX_REPLY_POLLS, POLL_SOFTWARE_ID,
    RUNTIME_SOFTWARE_IDS,
)
from tests.test_logi_discovery import ScriptedHid, candidate


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now


class DeferredHid(ScriptedHid):
    def __init__(self, clock, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clock = clock
        self.deferred = []

    def write(self, packet):
        pending, self.pending = self.pending, deque()
        self.respond(packet)
        generated = list(self.pending)
        self.pending = pending
        self.pending.extend(self.deferred)
        self.deferred = generated

    def respond(self, packet):
        super().write(packet)

    def read(self, size, timeout=1):
        self.clock.now += max(1, timeout) / 1000
        return super().read(size, timeout)


class DelayedReplyTests(unittest.TestCase):
    def test_software_id_pools_are_disjoint_and_never_notifications(self):
        discovery_ids, runtime_ids = set(DISCOVERY_SOFTWARE_IDS), set(RUNTIME_SOFTWARE_IDS)
        self.assertFalse(discovery_ids & runtime_ids)
        self.assertNotIn(POLL_SOFTWARE_ID, discovery_ids | runtime_ids)
        self.assertEqual(discovery_ids | runtime_ids | {POLL_SOFTWARE_ID}, set(range(1, 16)))

    def test_delayed_identity_is_online_and_keeps_radio_serial(self):
        clock = Clock()
        dev = DeferredHid(clock, {1: (3, "MX Master 2S", "12345678")})
        paired = {"kind": "mouse", "serial": "A1B2C3D4", "name": "MX Master 2S"}
        with patch("time.monotonic", clock.monotonic):
            found = discovery.IdentityProbe(dev).device(candidate(), 1, paired)
        self.assertTrue(found.online)
        self.assertEqual(found.serial, paired["serial"])
        self.assertEqual(found.model_key, "mx_master_2s")
        self.assertTrue(any(p[3] == 0x10 | POLL_SOFTWARE_ID for p in dev.writes))
        normal = [p for p in dev.writes if p[3] & 15 != POLL_SOFTWARE_ID]
        self.assertTrue(all(dev.writes.count(p) == 1 for p in normal))

    def test_consecutive_feature_reads_do_not_accept_previous_feature_index(self):
        clock = Clock()
        dev = DeferredHid(clock, {1: (3, "MX Master 2S", "12345678")})
        listener = h.HidGestureListener()
        listener._dev, listener._dev_idx = dev, 1
        with patch("time.monotonic", clock.monotonic):
            self.assertEqual(listener._find_feature(5, timeout_ms=700), 7)
            self.assertEqual(listener._find_feature(3, timeout_ms=700), 8)
            self.assertIsNone(listener._find_feature(0x1B04, timeout_ms=700))
        requests = [p for p in dev.writes if p[3] & 15 != POLL_SOFTWARE_ID]
        self.assertEqual(len(requests), 3)
        self.assertEqual(len({p[3] for p in requests}), 3)

    def test_delayed_configuration_ack_does_not_repeat_the_configuration(self):
        class SetterHid(DeferredHid):
            def respond(self, packet):
                self.writes.append(packet)
                self.pending.append([0x11, packet[1], packet[2], packet[3], 0x55])

        clock = Clock()
        dev = SetterHid(clock)
        listener = h.HidGestureListener()
        listener._dev, listener._dev_idx = dev, 1
        with patch("time.monotonic", clock.monotonic):
            response = listener._request(9, 3, [0, 0xC3, 3], timeout_ms=700)
        self.assertIsNotNone(response)
        setters = [p for p in dev.writes if p[2] == 9]
        self.assertEqual(len(setters), 1)
        self.assertTrue(all(p[2:4] == [0, 0x10 | POLL_SOFTWARE_ID]
                            for p in dev.writes if p[2] != 9))

    def test_stale_ping_nonce_is_ignored_even_if_software_id_matches(self):
        dev = ScriptedHid({1: (3, "MX Master 2S", "12345678")})
        original = dev.write

        def write(packet):
            if packet[2] == 0 and packet[3] >> 4 == 1:
                dev.pending.append([0x11, 1, 0, packet[3], 4, 5, (packet[6] + 1) & 255])
            original(packet)

        dev.write = write
        found = discovery.IdentityProbe(dev).device(candidate(), 1)
        self.assertTrue(found.online)

    def test_offline_error_is_not_retried_or_interpreted_as_hidpp1_online(self):
        dev = ScriptedHid()

        def write(packet):
            dev.writes.append(packet)
            dev.pending.append([0x10, packet[1], 0x8F, packet[2], packet[3], 9, 0])

        dev.write = write
        probe = discovery.IdentityProbe(dev)
        self.assertIsNone(probe.device(candidate(), 1))
        self.assertEqual(probe.last_error, 9)
        self.assertEqual(len(dev.writes), 1)

    def test_silent_device_has_bounded_read_only_polls(self):
        class SilentHid(DeferredHid):
            def respond(self, packet):
                self.writes.append(packet)

        for runtime in (False, True):
            with self.subTest(runtime=runtime):
                clock = Clock()
                dev = SilentHid(clock)
                with patch("time.monotonic", clock.monotonic):
                    if runtime:
                        listener = h.HidGestureListener()
                        listener._dev, listener._dev_idx = dev, 1
                        self.assertIsNone(listener._request(9, 3, [], timeout_ms=700))
                    else:
                        self.assertIsNone(discovery.IdentityProbe(dev).request(1, 0, 1, [0, 0, 42]))
                self.assertEqual(len(dev.writes), 1 + MAX_REPLY_POLLS)
                self.assertLess(clock.now, 0.81)

    def test_cancelled_runtime_request_does_not_emit_a_poll(self):
        clock = Clock()
        dev = DeferredHid(clock, {1: (3, "Mouse", "12345678")})
        listener = h.HidGestureListener()
        listener._dev, listener._dev_idx = dev, 1

        def read(timeout):
            listener._stopping.set()
            clock.now += timeout / 1000
            return None

        with patch("time.monotonic", clock.monotonic), patch.object(listener, "_rx", side_effect=read):
            self.assertIsNone(listener._request(0, 0, [0, 5, 0], timeout_ms=700))
        self.assertEqual(len(dev.writes), 1)

    def test_receiver_register_reads_never_emit_a_mouse_ping(self):
        clock = Clock()
        dev = DeferredHid(clock)
        with patch("time.monotonic", clock.monotonic):
            self.assertIsNone(discovery.IdentityProbe(dev).receiver_info(0x20))
        self.assertEqual(len(dev.writes), 1)


if __name__ == "__main__":
    unittest.main()
