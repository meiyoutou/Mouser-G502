"""No-hardware tests of multi-device identity, selection and packet isolation."""
import copy
import contextlib
from collections import deque
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core import hid_gesture as h
from core.logi_discovery import (
    DiscoveredDevice, IdentityProbe, choose_device, inventory_candidates,
)


def candidate(pid=0xC52B, path="receiver", name="USB Receiver", usage=2):
    return {"product_id": pid, "path": path.encode(), "product_string": name,
            "usage_page": 0xFF00, "usage": usage, "transport": "USB"}


class ScriptedHid:
    """Answers identity reads, never accepts any configuration command."""
    def __init__(self, devices=None, pairing=None):
        self.devices = devices or {}
        self.pairing = pairing or {}
        self.pending = deque()
        self.writes = []
        self.close = Mock()
        self.open_path = Mock()
        self.set_nonblocking = Mock()

    def write(self, packet):
        self.writes.append(packet)
        _, slot, sub, addr, *params = packet
        payload = None
        if sub == 0x83 and addr == 0xB5 and slot == 255:
            payload = self.pairing.get(params[0])
        elif slot in self.devices:
            kind, name, serial = self.devices[slot]
            func = addr >> 4
            if sub == 0 and func == 1:
                payload = [2, 0, params[2]]
            elif sub == 0 and func == 0:
                payload = [{5: 7, 3: 8}.get((params[0] << 8) | params[1], 0)]
            elif sub == 7:
                payload = {0: [len(name)], 2: [kind]}.get(func)
                if func == 1:
                    payload = list(name.encode()[params[0]:params[0] + 16])
            elif sub == 8 and func == 0:
                payload = [1, *bytes.fromhex(serial)]
            else:
                raise AssertionError(f"Not an identity read: {packet}")
        if payload is not None:
            self.pending.append([0x11, slot, sub, addr, *payload])
        else:
            self.pending.append([0x11, slot, 0x8F, sub, addr, 2])

    def read(self, *args):
        return self.pending.popleft() if self.pending else []


class DiscoveryTests(unittest.TestCase):
    def test_receiver_mouse_and_keyboard_are_separate(self):
        pair = {0x20: [0x20, 0, 8, 0x40, 1, 0, 0, 1],
                0x21: [0x21, 0, 8, 0x40, 2, 0, 0, 2]}
        handle = ScriptedHid({2: (3, "MX Master 2S", "12345678")}, pair)
        found = IdentityProbe(handle).scan(candidate())
        self.assertEqual([(d.slot, d.kind) for d in found], [(1, "keyboard"), (2, "mouse")])
        self.assertEqual(choose_device(found).slot, 2)
        self.assertEqual(found[1].model_key, "mx_master_2s")
        self.assertFalse(any(p[1] == 1 for p in handle.writes))

    def test_receiver_two_mice_listed_without_diverting_either(self):
        handle = ScriptedHid({1: (3, "MX Master 2S", "12345678"),
                              3: (3, "MX Anywhere 2S", "87654321")})
        found = IdentityProbe(handle).scan(candidate())
        self.assertEqual([d.slot for d in found], [1, 3])
        self.assertEqual(choose_device(found, found[1].preference()).slot, 3)
        self.assertTrue(all(p[2] in (0, 7, 8, 0x83) for p in handle.writes))

    def test_paired_offline_mouse_is_visible_but_not_bound(self):
        handle = ScriptedHid(pairing={0x20: [0x20, 0, 8, 0x40, 2, 0, 0, 2]})
        found = IdentityProbe(handle).scan(candidate())
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].status, "offline")
        self.assertIsNone(choose_device(found))

    def test_bolt_pairing_layout_and_keyboard_exclusion(self):
        handle = ScriptedHid({4: (3, "MX Master 3S", "12345678")},
                             {0x54: [0x54, 2, 0x82, 0x40, 1, 2, 3, 4]})
        found = IdentityProbe(handle).scan(candidate(0xC548))
        self.assertEqual(found[0].slot, 4)
        self.assertEqual(found[0].wpid, "4082")
        self.assertEqual(found[0].transport, "Logi Bolt")

    def test_direct_known_usb_mouse_detected_without_gesture_feature(self):
        handle = ScriptedHid()
        device = IdentityProbe(handle).scan(candidate(0xC08B, "g502", "G502 HERO"))[0]
        self.assertTrue(device.online)
        self.assertEqual(device.model_key, "g502_hero")

    def test_bluetooth_enumeration_alone_does_not_claim_online(self):
        info = candidate(0xB023, "bt", "MX Master 3")
        info["transport"] = "Bluetooth"
        device = IdentityProbe(ScriptedHid()).scan(info)[0]
        self.assertFalse(device.online)

    def test_hidpp_keyboard_type_overrides_a_mouse_like_name(self):
        handle = ScriptedHid({255: (0, "Mystery Mouse", "12345678")})
        device = IdentityProbe(handle).scan(candidate(0xB001, "bt", "Mystery Mouse"))[0]
        self.assertEqual(device.kind, "keyboard")
        self.assertIsNone(choose_device([device]))

    def test_saved_identity_survives_slot_and_port_change(self):
        old = DiscoveredDevice(candidate(), 1, "MX Master 2S", "mouse", "12345678", True)
        new = DiscoveredDevice(candidate(path="other-port"), 4, "MX Master 2S", "mouse", "12345678", True)
        self.assertEqual(old.identity, new.identity)
        self.assertIs(choose_device([new], old.preference()), new)

    def test_repaired_same_slot_does_not_reuse_previous_selection(self):
        old = DiscoveredDevice(candidate(), 1, "MX Master 2S", "mouse", "12345678", True)
        other = DiscoveredDevice(candidate(), 1, "MX Master 2S", "mouse", "87654321", True)
        self.assertIsNone(choose_device([other], old.preference()))

    def test_serialless_identity_does_not_follow_bare_slot_or_name(self):
        old = DiscoveredDevice(candidate(path="port-one"), 1, "Mouse", "mouse", online=True)
        other = DiscoveredDevice(candidate(path="port-two"), 1, "Mouse", "mouse", online=True)
        self.assertIsNone(choose_device([other], old.preference()))

    def test_offline_preference_does_not_switch_to_second_mouse(self):
        old = DiscoveredDevice(candidate(), 1, "Mouse", "mouse", online=False)
        other = DiscoveredDevice(candidate(), 2, "Mouse", "mouse", online=True)
        self.assertIsNone(choose_device([old, other], old.preference()))

    def test_duplicate_identity_selection_fails_closed(self):
        d = DiscoveredDevice(candidate(), 1, "Mouse", "mouse", "12345678", True)
        self.assertIsNone(choose_device([d, copy.copy(d)], d.preference()))

    def test_receiver_report_collections_are_deduplicated_long_first(self):
        a = candidate(path=r"hid#vid_046d&pid_c52b&mi_02&col01#7&x&0&0000#{guid}", usage=1)
        b = candidate(path=r"hid#vid_046d&pid_c52b&mi_02&col02#7&x&0&0001#{guid}", usage=2)
        self.assertEqual(inventory_candidates([a, b]), [dict(b, hidpp_short_path=a["path"])])

    def test_receiver_radio_serial_stays_stable_while_awake_and_asleep(self):
        pair = {0x20: [0x20, 0, 8, 0x40, 1, 0, 0, 2],
                0x30: [0x30, 1, 2, 3, 4]}
        awake = IdentityProbe(ScriptedHid({1: (3, "MX Master 2S", "12345678")}, pair)).scan(candidate())[0]
        asleep = IdentityProbe(ScriptedHid(pairing=pair)).scan(candidate())[0]
        self.assertEqual(awake.serial, "01020304")
        self.assertEqual(awake.identity, asleep.identity)
        self.assertTrue(awake.online)
        self.assertFalse(asleep.online)

    def test_pairing_read_uses_short_output_and_long_reply(self):
        long = ScriptedHid()
        short = SimpleNamespace(write=Mock(), read=Mock(return_value=[]))
        long.pending.append([0x11, 255, 0x83, 0xB5, 0x20, 0, 8, 0x40, 1, 0, 0, 2])
        result = IdentityProbe(long, short_handle=short).receiver_info(0x20)
        self.assertIsNotNone(result)
        short.write.assert_called_once_with([0x10, 255, 0x83, 0xB5, 0x20, 0, 0])
        self.assertEqual(long.writes, [])

    def test_auto_selection_also_refuses_duplicate_serials(self):
        d = DiscoveredDevice(candidate(), 1, "Mouse", "mouse", "12345678", True)
        self.assertIsNone(choose_device([d, copy.copy(d)]))

    def test_serial_with_zero_and_f_digits_is_not_a_placeholder(self):
        d = IdentityProbe(ScriptedHid({1: (3, "MX Master 2S", "0F0F0F0F")})).device(candidate(), 1)
        self.assertEqual(d.serial, "0F0F0F0F")

    def test_cancelled_probe_never_sends_a_request(self):
        dev = ScriptedHid()
        self.assertIsNone(IdentityProbe(dev, cancelled=lambda: True).request(1, 0, 1))
        self.assertEqual(dev.writes, [])

    def test_direct_mouse_interfaces_choose_one_vendor_channel(self):
        mouse = candidate(0xC08B, r"hid#vid_046d&pid_c08b&mi_00#7&device&0&0000#{guid}", "G502 HERO")
        mouse.update(usage_page=1, usage=2)
        vendor = candidate(0xC08B, r"hid#vid_046d&pid_c08b&mi_01&col02#7&device&0&0001#{guid}", "G502 HERO")
        other = candidate(0xC08B, r"hid#vid_046d&pid_c08b&mi_01&col02#7&otherdevice&0&0001#{guid}", "G502 HERO")
        self.assertEqual(inventory_candidates([mouse, vendor, other]), [vendor, other])

    def test_hidpp2_unsupported_ping_is_not_misclassified_as_awake_hidpp1(self):
        dev = ScriptedHid()
        def error(packet):
            dev.pending.append([0x11, packet[1], 0xFF, packet[2], packet[3], 1])
        dev.write = error
        self.assertIsNone(IdentityProbe(dev).device(candidate(), 1))


class PacketIsolationTests(unittest.TestCase):
    def test_other_slot_link_event_requests_scan_without_dispatch_or_invalidating_target(self):
        l = h.HidGestureListener(on_down=Mock())
        l._inventory_enabled = True
        l._inventory_target = DiscoveredDevice(candidate(), 1, "Mouse", "mouse", "12345678", True)
        l._dev_idx = 1
        l._on_report([0x10, 2, 0x41, 0x04, 0, 1, 0x40])
        self.assertTrue(l._inventory_refresh_requested.is_set())
        self.assertFalse(l._binding_invalidated)
        l._on_down.assert_not_called()

    def test_selected_slot_link_event_invalidates_old_configuration_until_revalidated(self):
        l = h.HidGestureListener()
        l._inventory_enabled = True
        l._inventory_target = DiscoveredDevice(candidate(), 1, "Mouse", "mouse", "12345678", True)
        l._dev_idx = 1
        l._on_report([0x10, 1, 0x41, 0x04, 0, 1, 0x40])
        self.assertTrue(l._binding_invalidated)
        self.assertTrue(l._inventory_refresh_requested.is_set())

    def test_invalidated_slot_cannot_receive_feature_commands(self):
        l = h.HidGestureListener()
        l._dev = SimpleNamespace(write=Mock())
        l._binding_invalidated = True
        with self.assertRaises(IOError):
            l._tx(0x11, 9, 3, [0, 0xC3, 3])
        l._dev.write.assert_not_called()

    def test_foreign_slot_button_and_battery_never_dispatch(self):
        down = Mock()
        l = h.HidGestureListener(on_down=down)
        l._dev_idx, l._feat_idx, l._gesture_cid = 1, 9, 0xC3
        l._on_report([0x11, 2, 9, 0, 0, 0xC3, 0, 0])
        down.assert_not_called()
        l._battery_idx = 9
        with patch.object(l, "_handle_battery_notification") as battery:
            l._on_report([0x11, 2, 9, 0, 50, 0, 0, 0])
            battery.assert_not_called()

    def test_correct_slot_notification_still_dispatches(self):
        down = Mock()
        l = h.HidGestureListener(on_down=down)
        l._dev_idx, l._feat_idx, l._gesture_cid = 1, 9, 0xC3
        l._on_report([0x11, 1, 9, 0, 0, 0xC3, 0, 0])
        down.assert_called_once()

    def test_other_software_reply_is_not_a_button_notification(self):
        l = h.HidGestureListener(on_down=Mock())
        l._dev_idx, l._feat_idx, l._gesture_cid = 1, 9, 0xC3
        l._on_report([0x11, 1, 9, h.MY_SW, 0, 0xC3, 0, 0])
        l._on_down.assert_not_called()

    def test_request_skips_foreign_reply_and_foreign_error(self):
        l = h.HidGestureListener()
        l._dev_idx = 1
        reports = [[0x11, 2, 9, h.MY_SW, 66],
                   [0x11, 2, 0xFF, 9, h.MY_SW, 2],
                   [0x11, 1, 9, h.MY_SW, 77]]
        with patch.object(l, "_tx"), patch.object(l, "_rx", side_effect=reports):
            self.assertEqual(l._request(9, 0, [])[4][0], 77)

    def test_request_keeps_other_slot_topology_event_for_rescan(self):
        l = h.HidGestureListener()
        l._inventory_enabled = True
        l._inventory_target = DiscoveredDevice(candidate(), 1, "Mouse", "mouse", "12345678", True)
        l._dev_idx = 1
        reports = [[0x10, 2, 0x41, 4, 0, 1, 0x40], [0x11, 1, 9, h.MY_SW, 77]]
        with patch.object(l, "_tx"), patch.object(l, "_rx", side_effect=reports):
            self.assertIsNotNone(l._request(9, 0, []))
        self.assertTrue(l._inventory_refresh_requested.is_set())
        self.assertFalse(l._binding_invalidated)

    def test_unrelated_error_on_same_slot_does_not_abort_request(self):
        l = h.HidGestureListener()
        l._dev_idx = 1
        reports = [[0x11, 1, 0xFF, 8, h.MY_SW, 2],
                   [0x11, 1, 9, h.MY_SW, 77]]
        with patch.object(l, "_tx"), patch.object(l, "_rx", side_effect=reports):
            self.assertIsNotNone(l._request(9, 0, []))

    def test_matching_error_is_still_rejected(self):
        l = h.HidGestureListener()
        l._dev_idx = 1
        with patch.object(l, "_tx"), patch.object(l, "_rx", return_value=[0x11, 1, 0xFF, 9, h.MY_SW, 2]):
            self.assertIsNone(l._request(9, 0, []))

    def test_probe_routes_live_notifications_while_waiting_for_another_slot(self):
        handle = ScriptedHid({2: (3, "Mouse", "12345678")})
        handle.pending.append([0x11, 1, 9, 0, 0, 0xC3, 0, 0])
        forward = Mock()
        probe = IdentityProbe(handle, forward)
        self.assertIsNotNone(probe.request(2, 0, 1, [0, 0, 0x5A]))
        forward.assert_called_once()


class InventoryIntegrationTests(unittest.TestCase):
    def test_owned_inventory_opens_and_closes_each_report_channel_once(self):
        l = h.HidGestureListener()
        long, short = ScriptedHid(), ScriptedHid()
        info = dict(candidate(), hidpp_short_path=b"short")
        with patch.object(h, "HIDAPI_OK", True), patch.object(h, "_HID_API_STYLE", "hidapi"), \
             patch.object(h, "_hid", SimpleNamespace(device=Mock(side_effect=[long, short]))):
            l._refresh_device_inventory([info])
        long.close.assert_called_once()
        short.close.assert_called_once()
        long.open_path.assert_called_once_with(b"receiver")
        short.open_path.assert_called_once_with(b"short")

    def test_runtime_receives_short_link_notifications_without_a_second_long_reader(self):
        l = h.HidGestureListener()
        packet = [0x10, 2, 0x41, 4, 0, 0, 0]
        l._dev = SimpleNamespace(read=Mock())
        l._short_dev = SimpleNamespace(read=Mock(return_value=packet))
        self.assertEqual(l._rx(200), packet)
        l._dev.read.assert_not_called()

    def test_stop_closes_secondary_channel(self):
        l = h.HidGestureListener()
        short = SimpleNamespace(close=Mock())
        l._short_dev = short
        l.stop()
        short.close.assert_called_once()
        self.assertIsNone(l._short_dev)

    @contextlib.contextmanager
    def connecting(self, listener, device):
        with contextlib.ExitStack() as stack:
            for cm in (
                patch.object(h, "HIDAPI_OK", True),
                patch.object(h, "_BACKEND_PREFERENCE", "hidapi"),
                patch.object(h, "_HID_API_STYLE", "hidapi"),
                patch.object(h, "_hid", SimpleNamespace(device=lambda: device)),
                patch.object(h, "_load_last_device_cache", return_value=None),
                patch.object(h, "_save_last_device_cache"),
                patch.object(listener, "_vendor_hid_infos", return_value=[candidate()]),
                patch.object(listener, "_find_feature", return_value=None),
            ):
                stack.enter_context(cm)
            yield

    def test_verified_mouse_connects_without_gesture_feature(self):
        l = h.HidGestureListener()
        l._inventory_enabled = True
        dev = ScriptedHid({2: (3, "MX Master 2S", "12345678")})
        with self.connecting(l, dev), patch.object(l, "_divert") as divert:
            self.assertTrue(l._try_connect())
        self.assertEqual(l._dev_idx, 2)
        self.assertEqual(l._inventory_target.status, "limited")
        self.assertEqual(l.connected_device.display_name, "MX Master 2S")
        divert.assert_not_called()

    def test_preferred_second_mouse_is_only_slot_used_for_feature_commands(self):
        l = h.HidGestureListener()
        l._inventory_enabled = True
        l._inventory_preference = DiscoveredDevice(candidate(), 3, "MX Anywhere 2S", "mouse", "87654321").preference()
        dev = ScriptedHid({1: (3, "MX Master 2S", "12345678"), 3: (3, "MX Anywhere 2S", "87654321")})
        slots = []
        def feature(*args, **kwargs):
            slots.append(l._dev_idx)
            return None
        with self.connecting(l, dev), patch.object(l, "_find_feature", side_effect=feature):
            self.assertTrue(l._try_connect())
        self.assertTrue(slots)
        self.assertEqual(set(slots), {3})

    def test_repaired_slot_is_rejected_before_any_feature_configuration(self):
        l = h.HidGestureListener()
        l._inventory_enabled = True
        old = DiscoveredDevice(candidate(), 1, "MX Master 2S", "mouse", "12345678", True)
        dev = ScriptedHid({1: (3, "MX Master 2S", "87654321")})
        with self.connecting(l, dev), patch.object(l, "_refresh_device_inventory", return_value=old), \
             patch.object(l, "_find_feature") as features, patch.object(l, "_divert") as divert:
            self.assertFalse(l._try_connect())
        features.assert_not_called()
        divert.assert_not_called()
        self.assertIsNone(l._dev)

    def test_serial_moving_to_another_slot_requires_reconnect(self):
        l = h.HidGestureListener()
        l._inventory_enabled = True
        l._inventory_target = DiscoveredDevice(candidate(), 1, "Mouse", "mouse", "12345678", True)
        moved = DiscoveredDevice(candidate(), 3, "Mouse", "mouse", "12345678", True)
        l._inventory_refresh_requested.set()
        with patch.object(l, "_vendor_hid_infos", return_value=[candidate()]), \
             patch.object(l, "_refresh_device_inventory", return_value=moved):
            with self.assertRaises(IOError):
                l._poll_inventory_changes()
        self.assertTrue(l._binding_invalidated)

    def test_stopped_inventory_does_not_open_another_handle(self):
        l = h.HidGestureListener()
        l._stopping.set()
        api = SimpleNamespace(device=Mock())
        with patch.object(h, "_hid", api):
            self.assertIsNone(l._refresh_device_inventory([candidate()]))
        api.device.assert_not_called()

    def test_scan_closes_owned_handles_and_does_not_divert(self):
        l = h.HidGestureListener()
        dev = ScriptedHid({1: (3, "MX Master 2S", "12345678")})
        with patch.object(h, "HIDAPI_OK", True), patch.object(h, "_HID_API_STYLE", "hidapi"), \
             patch.object(h, "_hid", SimpleNamespace(device=lambda: dev)), patch.object(l, "_divert") as divert:
            selected = l._refresh_device_inventory([candidate()])
        self.assertEqual(selected.slot, 1)
        dev.close.assert_called_once()
        divert.assert_not_called()

    def test_live_receiver_scan_reuses_single_reader(self):
        l = h.HidGestureListener()
        dev = ScriptedHid({1: (3, "MX Master 2S", "12345678")})
        l._dev = dev
        l._inventory_target = DiscoveredDevice(candidate(), 1, "MX Master 2S", "mouse", "12345678", True)
        with patch.object(h, "_hid", SimpleNamespace(device=Mock())) as api:
            selected = l._refresh_device_inventory([candidate()], live=True)
            api.device.assert_not_called()
        dev.close.assert_not_called()
        self.assertEqual(selected.slot, 1)


if __name__ == "__main__":
    unittest.main()
