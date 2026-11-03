"""Read-only Logitech inventory, separate from button diversion.

HID++ identity and pairing layouts follow pwr-Solaar/Solaar's hidpp20.py,
hidpp20_constants.py and receiver.py. No pairing, configuration or onboard
memory writes are issued here. The listener thread owns all live-handle I/O.
"""

from dataclasses import dataclass, field
import hashlib
import re
import time

from core.logi_devices import resolve_device

RECEIVER_PIDS = {0xC52B, 0xC532, 0xC534, 0xC539, 0xC53A, 0xC53F, 0xC548}
HIDPP2_KINDS = {0: "keyboard", 1: "remote", 2: "numpad", 3: "mouse",
               4: "touchpad", 5: "trackball", 6: "presenter", 7: "receiver"}
PAIRING_KINDS = {1: "keyboard", 2: "mouse", 3: "numpad", 4: "presenter",
                 8: "trackball", 9: "touchpad"}


def path_text(path):
    return path.decode("utf-8", errors="replace") if isinstance(path, bytes) else str(path or "")


def interface_group(info):
    """Group Windows report collections, not different receivers or ports."""
    path = path_text(info.get("path")).lower()
    if "&col" in path:
        path = re.sub(r"&col[0-9a-f]+", "", path)
        path = re.sub(r"&[0-9a-f]{4}(?=#\{)", "", path)
    return path


def is_receiver(info):
    return (int(info.get("product_id", 0)) in RECEIVER_PIDS
            or "receiver" in str(info.get("product_string") or "").lower())


def inventory_candidates(infos):
    groups = {}
    for info in infos:
        if is_receiver(info) and int(info.get("usage_page", 0)) != 0xFF00:
            continue  # consumer/DJ/keyboard collections are not HID++ channels
        key = interface_group(info)
        if not is_receiver(info):
            # A direct USB mouse may expose mouse, keyboard and vendor report
            # interfaces. Keep its instance prefix, but choose one HID++ reader.
            key = re.sub(r"&mi_[0-9a-f]{2}", "", key)
            key = re.sub(r"&[0-9a-f]{4}(?=#\{)", "", key)
        groups.setdefault(key, []).append(info)
    result = []
    for group in groups.values():
        # Long-report collection is essential when sending 20-byte requests.
        group.sort(key=lambda i: (int(i.get("usage_page", 0)) != 0xFF00,
                                  int(i.get("usage", 0)) != 2,
                                  int(i.get("usage", 0)) != 1))
        chosen = dict(group[0])
        short = next((i for i in group if i.get("usage_page") == 0xFF00 and i.get("usage") == 1), None)
        if is_receiver(chosen) and short and short.get("path") != chosen.get("path"):
            chosen["hidpp_short_path"] = short["path"]
        result.append(chosen)
    return result


def _serial(value):
    value = str(value or "").strip().upper()
    compact = value.replace("-", "")
    return "" if not compact or set(compact) in ({"0"}, {"F"}) else value


@dataclass
class DiscoveredDevice:
    candidate: dict = field(repr=False)
    slot: int = 0xFF
    name: str = ""
    kind: str = "unknown"
    serial: str = ""
    online: bool = False
    status: str = "communication_failed"
    protocol: str = ""
    model_key: str = ""
    wpid: str = ""

    @property
    def transport(self):
        if is_receiver(self.candidate):
            return "Logi Bolt" if int(self.candidate.get("product_id", 0)) == 0xC548 else "USB Receiver"
        if "bluetooth" in str(self.candidate.get("transport", "")).lower():
            return "Bluetooth"
        # Direct Bluetooth PIDs commonly start with B; metadata can be absent.
        return "Bluetooth" if (int(self.candidate.get("product_id", 0)) & 0xF000) == 0xB000 else "USB"

    @property
    def identity(self):
        # A verified serial survives USB port changes and slot reassignment.
        # Without one, retain exact topology AND model, never a bare slot.
        if self.serial:
            raw = f"serial:{self.kind}:{self.serial}"
        else:
            raw = f"path:{interface_group(self.candidate)}:{self.slot}:{self.kind}:{self.name}:{self.wpid}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def preference(self):
        return {"identity": self.identity, "name": self.name, "serial": self.serial,
                "kind": self.kind, "model_key": self.model_key}

    def to_dict(self):
        return {**self.preference(), "slot": self.slot, "transport": self.transport,
                "online": self.online, "status": self.status,
                "protocol": self.protocol, "model_confirmed": bool(self.model_key),
                "mouse": self.kind in ("mouse", "trackball")}


def choose_device(devices, preferred=None):
    mice = [d for d in devices if d.kind in ("mouse", "trackball")]
    if preferred and preferred.get("identity"):
        matching = [d for d in mice if d.identity == preferred["identity"]]
        # Ambiguous serials must not silently bind to the first device.
        return matching[0] if len(matching) == 1 and matching[0].online else None
    return next((d for d in mice if d.online
                 and sum(other.identity == d.identity for other in mice) == 1), None)


class IdentityProbe:
    """Bounded read-only requests. Can reuse the listener's active handle."""

    SW = 0x0D  # distinct from runtime requests

    def __init__(self, handle, on_unmatched=None, cancelled=None, timeout_ms=220, short_handle=None):
        self.handle = handle
        self.short_handle = short_handle
        self.on_unmatched = on_unmatched
        self.cancelled = cancelled or (lambda: False)
        self.timeout_ms = timeout_ms
        self.last_error = None
        self.last_error_protocol = None

    def exchange(self, slot, sub, address, params, *, register=False):
        self.last_error = None
        self.last_error_protocol = None
        if self.cancelled():
            return None
        size = 7 if register else 20
        packet = [0x10 if register else 0x11, slot, sub, address, *params]
        packet.extend([0] * (size - len(packet)))
        tx = (self.short_handle or self.handle) if register else self.handle
        tx.write(packet[:size])
        deadline = time.monotonic() + self.timeout_ms / 1000
        while time.monotonic() < deadline and not self.cancelled():
            remaining = max(1, int((deadline - time.monotonic()) * 1000))
            raw = list(self.short_handle.read(64, 1) or []) if self.short_handle else []
            if not raw:
                raw = list(self.handle.read(64, min(80, remaining)) or [])
            msg = raw[1:] if raw and raw[0] in (0x10, 0x11) else raw
            if len(msg) < 3:
                continue
            dev, rsub, raddr = msg[:3]
            payload = msg[3:]
            if dev == slot:
                if rsub == sub and raddr == address:
                    if not register or (payload and payload[0] == params[0]):
                        return payload
                if rsub == 0x8F and len(payload) >= 2 and raddr == sub and payload[0] == address:
                    self.last_error = payload[1]
                    self.last_error_protocol = "hidpp1"
                    return None
                if rsub == 0xFF and raddr == sub and len(payload) >= 2 and payload[0] == address:
                    self.last_error = payload[1]
                    self.last_error_protocol = "hidpp2"
                    return None
            if self.on_unmatched:
                self.on_unmatched(raw)
        return None

    def request(self, slot, feature, func=0, params=()):
        return self.exchange(slot, feature, (func << 4) | self.SW, list(params))

    def feature(self, slot, feature_id):
        result = self.request(slot, 0, 0, [feature_id >> 8, feature_id & 0xFF, 0])
        return result[0] if result and result[0] else None

    def receiver_info(self, sub, extra=()):
        return self.exchange(0xFF, 0x83, 0xB5, [sub, *extra], register=True)

    def pairing(self, slot, bolt=False):
        result = self.receiver_info(0x50 + slot if bolt else 0x20 + slot - 1)
        if not result or len(result) < 8:
            return {}
        if bolt:
            kind = PAIRING_KINDS.get(result[1] & 0x0F, "unknown")
            serial = bytes(result[4:8]).hex()
            wpid = bytes([result[3], result[2]]).hex()
            code = self.receiver_info(0x60 + slot, [1])
            name = bytes(code[3:3 + min(14, code[2])]).decode("utf-8", "replace") if code and len(code) > 3 else ""
        else:
            kind = PAIRING_KINDS.get(result[7] & 0x0F, "unknown")
            extended = self.receiver_info(0x30 + slot - 1)
            serial = bytes(extended[1:5]).hex() if extended and len(extended) >= 5 else ""
            wpid = bytes(result[3:5]).hex()
            code = self.receiver_info(0x40 + slot - 1)
            name = bytes(code[2:2 + min(14, code[1])]).decode("utf-8", "replace") if code and len(code) > 2 else ""
        return {"kind": kind, "serial": _serial(serial), "wpid": wpid.upper(), "name": name}

    def device(self, candidate, slot, paired=None):
        paired = paired or {}
        receiver = is_receiver(candidate)
        name = paired.get("name", "") if receiver else str(candidate.get("product_string") or "")
        kind = paired.get("kind", "unknown")
        serial = paired.get("serial", "") if receiver else _serial(candidate.get("serial_number"))
        if kind not in ("unknown", "mouse", "trackball"):
            return DiscoveredDevice(candidate, slot, name, kind, serial, status="paired", wpid=paired.get("wpid", ""))
        ping = self.request(slot, 0, 1, [0, 0, 0x5A])
        online = bool(ping and len(ping) >= 3 and ping[2] == 0x5A)
        protocol = "hidpp2" if online else ""
        # A matching HID++ 1.0 invalid-sub-id error proves the slot is awake.
        if not online and self.last_error == 1 and self.last_error_protocol == "hidpp1":
            online, protocol = True, "hidpp1"
        if protocol == "hidpp2":
            name_feature = self.feature(slot, 0x0005)
            if name_feature:
                typed = self.request(slot, name_feature, 2)
                if typed:
                    kind = HIDPP2_KINDS.get(typed[0], "unknown")
                length = self.request(slot, name_feature)
                if length and 0 < length[0] <= 255:
                    chunks = []
                    while len(chunks) < length[0] and not self.cancelled():
                        chunk = self.request(slot, name_feature, 1, [len(chunks)])
                        if not chunk:
                            break
                        chunks.extend(chunk[:length[0] - len(chunks)])
                    if len(chunks) == length[0]:
                        name = bytes(chunks).decode("utf-8", "replace").strip("\x00 ")
            firmware_feature = self.feature(slot, 0x0003)
            ids = self.request(slot, firmware_feature) if firmware_feature else None
            if ids and len(ids) >= 5:
                # Receiver radio serial and firmware unit ID can differ. Keep
                # the radio serial so awake/asleep inventories identify the
                # same paired mouse rather than two different management targets.
                unit_id = _serial(bytes(ids[1:5]).hex())
                serial = (serial or unit_id) if receiver else (unit_id or serial)
        spec = resolve_device(product_id=None if receiver else candidate.get("product_id"), product_name=name)
        if kind == "unknown" and (spec or "mouse" in name.lower()
                                  or (not receiver and candidate.get("usage_page") == 1 and candidate.get("usage") == 2)):
            kind = "mouse"
        # Direct USB mice remain detectable even without an HID++ identity
        # feature. Enumerability does NOT prove a Bluetooth mouse is awake.
        usb = not receiver and (int(candidate.get("product_id", 0)) & 0xF000) != 0xB000 and "bluetooth" not in str(candidate.get("transport", "")).lower()
        if usb and kind == "mouse":
            online = True
        if not online and not paired and receiver:
            return None
        status = "online" if online else ("offline" if paired else "communication_failed")
        return DiscoveredDevice(candidate, slot, name, kind, serial, online, status,
                                protocol, spec.key if spec else "", paired.get("wpid", ""))

    def scan(self, candidate):
        if not is_receiver(candidate):
            return [self.device(candidate, 0xFF)]
        result = []
        for slot in range(1, 7):
            if self.cancelled():
                break
            paired = self.pairing(slot, int(candidate.get("product_id", 0)) == 0xC548)
            device = self.device(candidate, slot, paired)
            if device is not None:
                result.append(device)
        return result
