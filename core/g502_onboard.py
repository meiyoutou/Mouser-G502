"""Safe Logitech G502 HERO onboard-profile backup and button unlock helpers.

The G502 HERO keeps DPI/profile/sniper buttons inside its onboard profile as
firmware "special" actions. Those actions do not necessarily produce host
events, so Mouser cannot remap them until the onboard profile is changed to
emit keyboard usages that Windows exposes reliably.

This module intentionally implements a very small, conservative subset of the
HID++ 2.0 ONBOARD_PROFILES feature:

* G502 HERO USB only (VID:PID 046D:C08B)
* read and export the profile directory plus user profile sectors
* restore sectors exactly from a Mouser backup JSON
* remap only the active profile's known special actions:
  DPI Shift, DPI down, DPI up, and profile cycle

Every mutating entry point creates/uses a complete backup first.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core import hid_gesture as _hg


LOGITECH_VENDOR_ID = 0x046D
G502_HERO_PRODUCT_ID = 0xC08B
SUPPORTED_PRODUCT_IDS = {G502_HERO_PRODUCT_ID}

FEAT_ONBOARD_PROFILES = 0x8100

CMD_GET_PROFILES_DESC = 0x00
CMD_SET_ONBOARD_MODE = 0x01
CMD_GET_ONBOARD_MODE = 0x02
CMD_SET_CURRENT_PROFILE = 0x03
CMD_GET_CURRENT_PROFILE = 0x04
CMD_MEMORY_READ = 0x05
CMD_MEMORY_ADDR_WRITE = 0x06
CMD_MEMORY_WRITE = 0x07
CMD_MEMORY_WRITE_END = 0x08

ONBOARD_MODE = 0x01
HOST_MODE = 0x02

SUPPORTED_MEMORY_MODEL = 0x01
SUPPORTED_MACRO_FORMAT = 0x01
SUPPORTED_PROFILE_FORMATS = {0x01, 0x02, 0x03, 0x04, 0x05}

PROFILE_BUTTON_OFFSET = 32
BUTTON_BINDING_SIZE = 4
MAX_REASONABLE_SECTOR_SIZE = 4096

SPECIAL_DPI_UP = 0x03
SPECIAL_DPI_DOWN = 0x04
SPECIAL_DPI_SHIFT = 0x07
SPECIAL_PROFILE_CYCLE = 0x0A
SPECIAL_WHEEL_LEFT = 0x01
SPECIAL_WHEEL_RIGHT = 0x02

SPECIAL_NAMES = {
    SPECIAL_WHEEL_LEFT: "wheel_left",
    SPECIAL_WHEEL_RIGHT: "wheel_right",
    SPECIAL_DPI_UP: "dpi_up",
    SPECIAL_DPI_DOWN: "dpi_down",
    0x05: "dpi_cycle",
    0x06: "default_dpi",
    SPECIAL_DPI_SHIFT: "dpi_shift",
    0x08: "profile_up",
    0x09: "profile_down",
    SPECIAL_PROFILE_CYCLE: "profile_cycle",
    0x0B: "g_shift",
}

UNLOCK_TARGETS = {
    SPECIAL_DPI_SHIFT: {
        "button_key": "g502_dpi_shift",
        "label": "DPI Shift / sniper",
        "fkey": "F13",
        "keyboard_usage": 0x68,
        "legacy_mouse_button": 6,
        "expected_button_index": 6,
    },
    SPECIAL_DPI_DOWN: {
        "button_key": "g502_dpi_down",
        "label": "DPI down",
        "fkey": "F14",
        "keyboard_usage": 0x69,
        "legacy_mouse_button": 9,
        "expected_button_index": 7,
    },
    SPECIAL_DPI_UP: {
        "button_key": "g502_dpi_up",
        "label": "DPI up",
        "fkey": "F15",
        "keyboard_usage": 0x6A,
        "legacy_mouse_button": 10,
        "expected_button_index": 8,
    },
    SPECIAL_PROFILE_CYCLE: {
        "button_key": "g502_profile_cycle",
        "label": "Profile cycle",
        "fkey": "F16",
        "keyboard_usage": 0x6B,
        "legacy_mouse_button": 11,
        "expected_button_index": 9,
    },
}

LEGACY_MOUSE_BUTTON_TARGETS_BY_INDEX = {
    int(target["expected_button_index"]): target for target in UNLOCK_TARGETS.values()
}

BACKUP_SCHEMA = "mouser.g502.onboard.backup.v1"


class G502OnboardError(RuntimeError):
    """Raised when the G502 onboard profile operation cannot be completed."""


@dataclass(frozen=True)
class ProfileDescriptor:
    memory_model_id: int
    profile_format_id: int
    macro_format_id: int
    profile_count: int
    profile_count_oob: int
    button_count: int
    sector_count: int
    sector_size: int
    mechanical_layout: int
    various_info: int
    raw: bytes

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ProfileDescriptor":
        if len(raw) < 10:
            raise G502OnboardError("G502 onboard profile descriptor is too short")
        sector_size = (raw[7] << 8) | raw[8]
        return cls(
            memory_model_id=raw[0],
            profile_format_id=raw[1],
            macro_format_id=raw[2],
            profile_count=raw[3],
            profile_count_oob=raw[4],
            button_count=raw[5],
            sector_count=raw[6],
            sector_size=sector_size,
            mechanical_layout=raw[9],
            various_info=raw[10] if len(raw) > 10 else 0,
            raw=bytes(raw),
        )

    def validate_for_g502_hero(self) -> None:
        if self.memory_model_id != SUPPORTED_MEMORY_MODEL:
            raise G502OnboardError(
                f"Unsupported G502 memory model 0x{self.memory_model_id:02X}"
            )
        if self.profile_format_id not in SUPPORTED_PROFILE_FORMATS:
            raise G502OnboardError(
                f"Unsupported G502 profile format 0x{self.profile_format_id:02X}"
            )
        if self.macro_format_id != SUPPORTED_MACRO_FORMAT:
            raise G502OnboardError(
                f"Unsupported G502 macro format 0x{self.macro_format_id:02X}"
            )
        if self.button_count <= 0 or self.button_count > 16:
            raise G502OnboardError(
                f"Unexpected G502 button count {self.button_count}"
            )
        if self.sector_count <= 0 or self.sector_count > 255:
            raise G502OnboardError(
                f"Unexpected G502 sector count {self.sector_count}"
            )
        if (
            self.sector_size < 128
            or self.sector_size > MAX_REASONABLE_SECTOR_SIZE
            or self.sector_size % 16 != 0
        ):
            raise G502OnboardError(
                f"Unexpected G502 sector size {self.sector_size}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_model_id": self.memory_model_id,
            "profile_format_id": self.profile_format_id,
            "macro_format_id": self.macro_format_id,
            "profile_count": self.profile_count,
            "profile_count_oob": self.profile_count_oob,
            "button_count": self.button_count,
            "sector_count": self.sector_count,
            "sector_size": self.sector_size,
            "mechanical_layout": self.mechanical_layout,
            "various_info": self.various_info,
            "raw_hex": self.raw.hex(),
        }


def default_backup_dir() -> Path:
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(root) / "Mouser" / "g502_backups"


def latest_backup_path(
    backup_dir: str | os.PathLike[str] | None = None,
    *,
    purpose: str | None = None,
) -> Path | None:
    root = Path(backup_dir) if backup_dir else default_backup_dir()
    try:
        candidates = sorted(
            root.glob("g502_onboard_backup_*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    if not purpose:
        return candidates[0] if candidates else None
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("purpose") == purpose:
            return candidate
    return None


def latest_before_unlock_backup_path(
    backup_dir: str | os.PathLike[str] | None = None,
) -> Path | None:
    root = Path(backup_dir) if backup_dir else default_backup_dir()
    try:
        candidates = sorted(
            root.glob("g502_onboard_backup_*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            payload.get("purpose") == "before_unlock"
            and _backup_has_locked_special_buttons(payload)
        ):
            return candidate
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _backup_has_locked_special_buttons(payload):
            return candidate
    return None


def backup_path_has_locked_special_buttons(path: str | os.PathLike[str]) -> bool:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return _backup_has_locked_special_buttons(payload)


def _backup_has_locked_special_buttons(payload: dict[str, Any]) -> bool:
    try:
        descriptor = payload.get("descriptor") or {}
        button_count = int(descriptor.get("button_count", 0) or 0)
        active_sector = int(payload.get("active_profile_sector"))
        sectors = payload.get("sectors") or {}
        active_hex = sectors.get(f"{active_sector:04X}")
        if not active_hex:
            return False
        sector = bytes.fromhex(active_hex)
    except (TypeError, ValueError):
        return False
    for binding in _profile_button_bindings(sector, button_count):
        if (
            binding.get("type") == "special"
            and binding.get("special") in UNLOCK_TARGETS
        ):
            return True
    return False


def crc16_ccitt(data: bytes | bytearray, initial: int = 0xFFFF) -> int:
    """CRC-CCITT variant used by Logitech G-series profile sectors."""
    crc = initial & 0xFFFF
    for b in data:
        crc ^= (int(b) & 0xFF) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF


def _hex_bytes(data: bytes | bytearray | list[int]) -> str:
    return " ".join(f"{int(b) & 0xFF:02X}" for b in data)


def mouse_button_binding(button_number: int) -> bytes:
    if button_number <= 0 or button_number > 16:
        raise ValueError("G502 unlock only supports mouse buttons 1-16")
    mask = 1 << (button_number - 1)
    return bytes((0x80, 0x01, (mask >> 8) & 0xFF, mask & 0xFF))


def keyboard_key_binding(usage_id: int, modifier: int = 0) -> bytes:
    if usage_id <= 0 or usage_id > 0xFF:
        raise ValueError("G502 unlock only supports one-byte keyboard usages")
    if modifier < 0 or modifier > 0xFF:
        raise ValueError("G502 unlock keyboard modifier must fit in one byte")
    return bytes((0x80, 0x02, modifier & 0xFF, usage_id & 0xFF))


def decode_button_binding(raw: bytes | bytearray) -> dict[str, Any]:
    b = bytes(raw[:BUTTON_BINDING_SIZE])
    if len(b) < BUTTON_BINDING_SIZE:
        b = b.ljust(BUTTON_BINDING_SIZE, b"\x00")
    result: dict[str, Any] = {"raw_hex": b.hex()}
    if b[0] == 0x80 and b[1] == 0x01:
        mask = (b[2] << 8) | b[3]
        result.update({"type": "mouse", "mask": mask})
        if mask:
            result["mouse_button"] = (mask & -mask).bit_length()
    elif b[0] == 0x80 and b[1] == 0x02:
        result.update({"type": "keyboard", "modifier": b[2], "key": b[3]})
        if 0x68 <= b[3] <= 0x73:
            result["key_name"] = f"F{int(b[3]) - 0x68 + 13}"
    elif b[0] == 0x80 and b[1] == 0x03:
        result.update({"type": "consumer", "usage": (b[2] << 8) | b[3]})
    elif b[0] == 0x90:
        result.update({
            "type": "special",
            "special": b[1],
            "special_name": SPECIAL_NAMES.get(b[1], f"0x{b[1]:02X}"),
            "profile": b[3],
        })
    elif b[0] == 0xFF:
        result["type"] = "disabled"
    elif b[0] == 0x00:
        result.update({"type": "macro", "page": b[1], "offset": b[3]})
    else:
        result["type"] = "unknown"
    return result


def _profile_button_bindings(sector_data: bytes | bytearray, button_count: int) -> list[dict[str, Any]]:
    out = []
    for index in range(max(0, min(int(button_count), 16))):
        offset = PROFILE_BUTTON_OFFSET + index * BUTTON_BINDING_SIZE
        raw = bytes(sector_data[offset:offset + BUTTON_BINDING_SIZE])
        decoded = decode_button_binding(raw)
        decoded.update({"index": index + 1, "offset": offset})
        out.append(decoded)
    return out


def _sector_crc_info(blob: bytes | bytearray) -> dict[str, Any]:
    if len(blob) < 2:
        return {"stored": None, "calculated": None, "valid": False}
    stored = (blob[-2] << 8) | blob[-1]
    calculated = crc16_ccitt(bytes(blob[:-2]))
    return {
        "stored": f"0x{stored:04X}",
        "calculated": f"0x{calculated:04X}",
        "valid": stored == calculated,
    }


class _HidppClient:
    def __init__(self, device: Any, info: dict[str, Any], dev_idx: int, onboard_idx: int):
        self.device = device
        self.info = info
        self.dev_idx = dev_idx
        self.onboard_idx = onboard_idx

    def close(self) -> None:
        try:
            self.device.close()
        except Exception:
            pass

    def request(
        self,
        feat_idx: int,
        func: int,
        params: bytes | bytearray | list[int] = b"",
        timeout_ms: int = 1500,
    ) -> bytes:
        payload = list(params)
        buf = [0] * _hg.LONG_LEN
        buf[0] = _hg.LONG_ID
        buf[1] = self.dev_idx & 0xFF
        buf[2] = feat_idx & 0xFF
        buf[3] = ((func & 0x0F) << 4) | (_hg.MY_SW & 0x0F)
        for i, b in enumerate(payload):
            if 4 + i < len(buf):
                buf[4 + i] = int(b) & 0xFF
        self.device.write(buf)

        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            raw = self.device.read(64, min(200, timeout_ms))
            if not raw:
                continue
            parsed = _hg._parse(list(raw))
            if parsed is None:
                continue
            _dev, r_feat, r_func, r_sw, r_params = parsed
            if r_feat == 0xFF:
                code = r_params[1] if len(r_params) > 1 else 0
                name = _hg.HIDPP_ERROR_NAMES.get(code, "UNKNOWN")
                raise G502OnboardError(
                    f"HID++ error 0x{code:02X} ({name}) for "
                    f"feature=0x{feat_idx:02X} function=0x{func:X}"
                )
            if (
                r_feat == (feat_idx & 0xFF)
                and r_sw == (_hg.MY_SW & 0x0F)
                and r_func in {func & 0x0F, (func + 1) & 0x0F}
            ):
                return bytes(r_params)
        raise G502OnboardError(
            f"HID++ request timed out for feature=0x{feat_idx:02X} "
            f"function=0x{func:X} params=[{_hex_bytes(payload)}]"
        )

    def get_descriptor(self) -> ProfileDescriptor:
        desc = ProfileDescriptor.from_bytes(
            self.request(self.onboard_idx, CMD_GET_PROFILES_DESC, b"")
        )
        desc.validate_for_g502_hero()
        return desc

    def get_onboard_mode(self) -> int | None:
        try:
            resp = self.request(self.onboard_idx, CMD_GET_ONBOARD_MODE, b"")
        except G502OnboardError:
            return None
        return resp[0] if resp else None

    def set_onboard_mode(self, mode: int) -> None:
        self.request(self.onboard_idx, CMD_SET_ONBOARD_MODE, bytes([mode & 0xFF]))

    def get_current_profile_value(self) -> int | None:
        try:
            resp = self.request(self.onboard_idx, CMD_GET_CURRENT_PROFILE, b"")
        except G502OnboardError:
            return None
        if len(resp) >= 2:
            return (resp[0] << 8) | resp[1]
        return resp[0] if resp else None

    def set_current_profile_value(self, value: int) -> None:
        self.request(
            self.onboard_idx,
            CMD_SET_CURRENT_PROFILE,
            bytes(((value >> 8) & 0xFF, value & 0xFF)),
        )

    def read_sector(self, sector: int, sector_size: int) -> bytes:
        if sector < 0:
            raise G502OnboardError("Negative sector is invalid")
        data = bytearray()
        offset = 0
        while offset < sector_size:
            read_offset = offset
            if sector_size - offset < 16:
                read_offset = max(0, sector_size - 16)
            chunk = self.request(
                self.onboard_idx,
                CMD_MEMORY_READ,
                bytes((
                    (sector >> 8) & 0xFF,
                    sector & 0xFF,
                    (read_offset >> 8) & 0xFF,
                    read_offset & 0xFF,
                )),
            )
            if len(chunk) < 16:
                raise G502OnboardError(
                    f"Short G502 sector read for sector 0x{sector:04X} "
                    f"offset 0x{read_offset:04X}"
                )
            if read_offset == offset:
                data.extend(chunk[: min(16, sector_size - offset)])
                offset += 16
            else:
                needed = sector_size - len(data)
                data.extend(chunk[16 - needed:16])
                break
        return bytes(data[:sector_size])

    def write_sector(
        self,
        sector: int,
        sector_data: bytes | bytearray,
        *,
        update_crc: bool = True,
    ) -> None:
        data = bytearray(sector_data)
        if len(data) < 16 or len(data) % 16 != 0:
            raise G502OnboardError("G502 sector length must be a positive multiple of 16")
        if update_crc:
            crc = crc16_ccitt(data[:-2])
            data[-2] = (crc >> 8) & 0xFF
            data[-1] = crc & 0xFF
        self.request(
            self.onboard_idx,
            CMD_MEMORY_ADDR_WRITE,
            bytes((
                (sector >> 8) & 0xFF,
                sector & 0xFF,
                0x00,
                0x00,
                (len(data) >> 8) & 0xFF,
                len(data) & 0xFF,
            )),
            timeout_ms=2500,
        )
        for offset in range(0, len(data), 16):
            self.request(
                self.onboard_idx,
                CMD_MEMORY_WRITE,
                bytes(data[offset:offset + 16]),
                timeout_ms=2500,
            )
        self.request(self.onboard_idx, CMD_MEMORY_WRITE_END, b"", timeout_ms=2500)


def _open_hidapi_device(info: dict[str, Any]):
    if _hg._HID_API_STYLE == "hidapi":
        dev = _hg._hid.device()
        dev.open_path(info["path"])
    else:
        dev = _hg._HidDeviceCompat(info["path"])
    dev.set_nonblocking(False)
    return dev


def _candidate_infos() -> list[dict[str, Any]]:
    if not _hg.HIDAPI_OK:
        raise G502OnboardError(
            f"HID backend is not available: {_hg.HIDAPI_IMPORT_ERROR!r}"
        )
    infos = []
    for info in _hg.HidGestureListener._vendor_hid_infos():
        pid = int(info.get("product_id", 0) or 0)
        usage_page = int(info.get("usage_page", 0) or 0)
        if pid not in SUPPORTED_PRODUCT_IDS:
            continue
        if usage_page < 0xFF00:
            continue
        if not info.get("path"):
            continue
        infos.append(info)
    if not infos:
        raise G502OnboardError(
            "No supported G502 HERO HID++ interface was found (expected 046D:C08B)"
        )
    infos.sort(key=lambda i: (0 if int(i.get("usage", 0) or 0) == 0x0002 else 1))
    return infos


def connect_g502_hero() -> _HidppClient:
    last_error: Exception | None = None
    for info in _candidate_infos():
        try:
            dev = _open_hidapi_device(info)
        except Exception as exc:  # noqa: BLE001 - report last useful error
            last_error = exc
            continue
        matched = False
        try:
            temp = _HidppClient(dev, info, 0xFF, 0)
            for dev_idx in (0xFF, 1, 2, 3, 4, 5, 6):
                temp.dev_idx = dev_idx
                try:
                    resp = temp.request(
                        0x00, 0x00, [0x81, 0x00, 0x00], timeout_ms=500
                    )
                except Exception as exc:  # noqa: BLE001 - try next index/candidate
                    last_error = exc
                    continue
                if resp and resp[0]:
                    temp.onboard_idx = resp[0]
                    matched = True
                    return temp
        finally:
            if not matched:
                try:
                    dev.close()
                except Exception:
                    pass
    if last_error:
        raise G502OnboardError(f"Could not open G502 onboard profile interface: {last_error}")
    raise G502OnboardError("Could not open G502 onboard profile interface")


def _parse_profile_headers(directory: bytes, descriptor: ProfileDescriptor) -> list[dict[str, Any]]:
    headers = []
    max_headers = min(descriptor.profile_count or 0, 16)
    for i in range(max_headers):
        off = i * 4
        if off + 3 >= len(directory):
            break
        sector = (directory[off] << 8) | directory[off + 1]
        enabled = directory[off + 2]
        if sector == 0xFFFF:
            break
        headers.append({
            "index": i + 1,
            "sector": sector,
            "enabled": enabled,
        })
    return headers


def _resolve_active_sector(current_value: int | None, headers: list[dict[str, Any]]) -> int:
    enabled = [h for h in headers if int(h.get("enabled", 0) or 0)]
    if current_value is not None:
        for h in headers:
            if int(h.get("sector", -1)) == current_value:
                return int(h["sector"])
        if 1 <= current_value <= len(headers):
            return int(headers[current_value - 1]["sector"])
    if enabled:
        return int(enabled[0]["sector"])
    if headers:
        return int(headers[0]["sector"])
    raise G502OnboardError("Could not determine the active G502 onboard profile")


def _backup_payload(client: _HidppClient) -> dict[str, Any]:
    descriptor = client.get_descriptor()
    mode = client.get_onboard_mode()
    current = client.get_current_profile_value()
    directory = client.read_sector(0, descriptor.sector_size)
    directory_crc = _sector_crc_info(directory)
    if not directory_crc.get("valid"):
        raise G502OnboardError(
            "G502 onboard profile directory CRC is invalid; refusing to continue"
        )
    headers = _parse_profile_headers(directory, descriptor)
    if not headers:
        raise G502OnboardError("No G502 onboard profile headers were found")
    sectors_to_read = sorted({
        0,
        *(
            int(h["sector"])
            for h in headers
            if 0 <= int(h["sector"]) < descriptor.sector_count
        ),
    })
    sectors: dict[str, str] = {}
    sector_crc: dict[str, dict[str, Any]] = {}
    profile_buttons: dict[str, list[dict[str, Any]]] = {}
    for sector in sectors_to_read:
        blob = client.read_sector(sector, descriptor.sector_size)
        key = f"{sector:04X}"
        sectors[key] = blob.hex()
        sector_crc[key] = _sector_crc_info(blob)
        if sector:
            profile_buttons[key] = _profile_button_bindings(
                blob,
                descriptor.button_count,
            )
    active_sector = _resolve_active_sector(current, headers)
    return {
        "schema": BACKUP_SCHEMA,
        "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "device": {
            "vendor_id": f"0x{LOGITECH_VENDOR_ID:04X}",
            "product_id": f"0x{int(client.info.get('product_id', 0) or 0):04X}",
            "product_string": client.info.get("product_string") or "",
            "usage_page": f"0x{int(client.info.get('usage_page', 0) or 0):04X}",
            "usage": f"0x{int(client.info.get('usage', 0) or 0):04X}",
            "path": _hg._device_path_display(client.info.get("path")) or "",
            "dev_idx": f"0x{client.dev_idx:02X}",
            "onboard_feature_index": f"0x{client.onboard_idx:02X}",
        },
        "descriptor": descriptor.to_dict(),
        "onboard_mode": mode,
        "current_profile_value": current,
        "active_profile_sector": active_sector,
        "profile_headers": headers,
        "sector_crc": sector_crc,
        "profile_buttons": profile_buttons,
        "sectors": sectors,
    }


def save_backup(
    payload: dict[str, Any],
    backup_dir: str | os.PathLike[str] | None = None,
) -> Path:
    root = Path(backup_dir) if backup_dir else default_backup_dir()
    root.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = root / f"g502_onboard_backup_{stamp}.json"
    suffix = 1
    while path.exists():
        path = root / f"g502_onboard_backup_{stamp}-{suffix}.json"
        suffix += 1
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _backup_sector_blob(sector_key: str, sector_hex: str, sector_size: int) -> bytes:
    try:
        sector = int(sector_key, 16)
    except (TypeError, ValueError) as exc:
        raise G502OnboardError(f"Backup sector key {sector_key!r} is invalid") from exc
    if sector < 0:
        raise G502OnboardError(f"Backup sector 0x{sector:04X} is invalid")
    try:
        blob = bytes.fromhex(str(sector_hex))
    except ValueError as exc:
        raise G502OnboardError(
            f"Backup sector 0x{sector:04X} contains invalid hex data"
        ) from exc
    if len(blob) != sector_size:
        raise G502OnboardError(
            f"Backup sector 0x{sector:04X} has invalid length"
        )
    crc = _sector_crc_info(blob)
    if not crc.get("valid"):
        raise G502OnboardError(
            f"Backup sector 0x{sector:04X} CRC is invalid; refusing to restore"
        )
    return blob


def backup_g502_hero(
    backup_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    client = connect_g502_hero()
    try:
        payload = _backup_payload(client)
        payload["purpose"] = "manual_backup"
        path = save_backup(payload, backup_dir)
        payload["backup_path"] = str(path)
        return payload
    finally:
        client.close()


def _apply_unlock_to_sector(
    sector_data: bytes | bytearray,
    button_count: int,
) -> tuple[bytes, list[dict[str, Any]]]:
    data = bytearray(sector_data)
    changes = []
    for index in range(max(0, min(int(button_count), 16))):
        offset = PROFILE_BUTTON_OFFSET + index * BUTTON_BINDING_SIZE
        current = bytes(data[offset:offset + BUTTON_BINDING_SIZE])
        if len(current) < BUTTON_BINDING_SIZE:
            break
        target = None
        if current[0] == 0x90:
            target = UNLOCK_TARGETS.get(current[1])
        else:
            # Migration path from Mouser's first G502 unlock build. That build
            # wrote high-numbered mouse buttons (6/9/10/11), but some Windows
            # systems do not surface those bits reliably. Only rewrite the exact
            # legacy value at the known G502 HERO table index, so unrelated
            # custom bindings are left untouched.
            by_index = LEGACY_MOUSE_BUTTON_TARGETS_BY_INDEX.get(index + 1)
            if by_index is not None:
                legacy = mouse_button_binding(int(by_index["legacy_mouse_button"]))
                if current == legacy:
                    target = by_index
        if not target:
            continue
        replacement = keyboard_key_binding(int(target["keyboard_usage"]))
        if current == replacement:
            continue
        data[offset:offset + BUTTON_BINDING_SIZE] = replacement
        changes.append({
            "button_index": index + 1,
            "offset": offset,
            "button_key": target["button_key"],
            "label": target["label"],
            "from": decode_button_binding(current),
            "to": decode_button_binding(replacement),
            "target_key": target["fkey"],
        })
    if changes:
        crc = crc16_ccitt(data[:-2])
        data[-2] = (crc >> 8) & 0xFF
        data[-1] = crc & 0xFF
    return bytes(data), changes


def unlock_g502_hero_buttons(
    backup_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Back up current onboard config, then remap active-profile special keys."""
    client = connect_g502_hero()
    backup_path: Path | None = None
    try:
        backup = _backup_payload(client)
        descriptor = ProfileDescriptor.from_bytes(
            bytes.fromhex(backup["descriptor"]["raw_hex"])
        )
        active_sector = int(backup["active_profile_sector"])
        active_key = f"{active_sector:04X}"
        if active_key not in backup["sectors"]:
            raise G502OnboardError(
                f"Active G502 profile sector 0x{active_sector:04X} was not backed up"
            )
        active_crc = backup["sector_crc"].get(active_key, {})
        if not active_crc.get("valid"):
            raise G502OnboardError(
                f"Active G502 profile sector 0x{active_sector:04X} has an invalid CRC"
            )
        old_sector = bytes.fromhex(backup["sectors"][active_key])
        new_sector, changes = _apply_unlock_to_sector(
            old_sector,
            descriptor.button_count,
        )
        backup["purpose"] = "before_unlock" if changes else "already_unlocked_snapshot"
        backup_path = save_backup(backup, backup_dir)
        mode_before = backup.get("onboard_mode")
        mode_changed = False
        if not changes:
            return {
                "ok": True,
                "changed": False,
                "backup_path": str(backup_path),
                "active_profile_sector": active_sector,
                "changes": [],
                "message": (
                    "G502 onboard buttons already emit F13-F16 or no "
                    "supported special actions were found."
                ),
            }
        if mode_before not in (None, ONBOARD_MODE):
            client.set_onboard_mode(ONBOARD_MODE)
            mode_changed = True
        client.write_sector(active_sector, new_sector, update_crc=False)
        try:
            client.set_current_profile_value(active_sector)
        except G502OnboardError:
            pass
        verify = client.read_sector(active_sector, descriptor.sector_size)
        verify_crc = _sector_crc_info(verify)
        if verify != new_sector or not verify_crc.get("valid"):
            raise G502OnboardError(
                "G502 onboard write verification failed; backup was saved but "
                "the profile did not read back as expected"
            )
        return {
            "ok": True,
            "changed": True,
            "backup_path": str(backup_path),
            "active_profile_sector": active_sector,
            "mode_changed_to_onboard": mode_changed,
            "changes": changes,
            "message": (
                "G502 onboard profile unlocked. DPI/Profile buttons now emit "
                "F13-F16 for Mouser to intercept."
            ),
        }
    except Exception as exc:
        if backup_path is not None and str(backup_path) not in str(exc):
            raise G502OnboardError(
                f"{exc}. Backup was saved at {backup_path}"
            ) from exc
        raise
    finally:
        client.close()


def restore_g502_hero_backup(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    backup_path = Path(path) if path else (
        latest_before_unlock_backup_path() or latest_backup_path()
    )
    if backup_path is None:
        raise G502OnboardError("No G502 onboard backup file was found")
    payload = json.loads(backup_path.read_text(encoding="utf-8"))
    if payload.get("schema") != BACKUP_SCHEMA:
        raise G502OnboardError("Selected file is not a Mouser G502 onboard backup")
    sectors = payload.get("sectors")
    if not isinstance(sectors, dict) or not sectors:
        raise G502OnboardError("Backup contains no G502 onboard sectors")
    descriptor_data = payload.get("descriptor") or {}
    sector_size = int(descriptor_data.get("sector_size", 0) or 0)
    if (
        sector_size < 128
        or sector_size > MAX_REASONABLE_SECTOR_SIZE
        or sector_size % 16 != 0
    ):
        raise G502OnboardError("Backup has an invalid G502 sector size")
    sector_blobs = {
        str(sector_key): _backup_sector_blob(str(sector_key), sector_hex, sector_size)
        for sector_key, sector_hex in sectors.items()
    }

    client = connect_g502_hero()
    restored = []
    mode_before = None
    try:
        live_desc = client.get_descriptor()
        if live_desc.sector_size != sector_size:
            raise G502OnboardError(
                "Connected G502 sector size does not match the backup"
            )
        for sector_key in sector_blobs:
            sector = int(sector_key, 16)
            if sector >= live_desc.sector_count:
                raise G502OnboardError(
                    f"Backup sector 0x{sector:04X} is outside the connected G502 memory"
                )
        mode_before = client.get_onboard_mode()
        if mode_before not in (None, ONBOARD_MODE):
            client.set_onboard_mode(ONBOARD_MODE)
        for sector_key in sorted(sector_blobs.keys(), key=lambda key: (int(key, 16) == 0, int(key, 16))):
            sector = int(sector_key, 16)
            blob = sector_blobs[sector_key]
            client.write_sector(sector, blob, update_crc=False)
            restored.append(sector)
        current = payload.get("current_profile_value")
        if isinstance(current, int):
            try:
                client.set_current_profile_value(current)
            except G502OnboardError:
                pass
        backup_mode = payload.get("onboard_mode")
        if isinstance(backup_mode, int) and backup_mode in (ONBOARD_MODE, HOST_MODE):
            try:
                client.set_onboard_mode(backup_mode)
            except G502OnboardError:
                pass
        return {
            "ok": True,
            "backup_path": str(backup_path),
            "restored_sectors": restored,
            "message": "G502 onboard backup restored.",
        }
    finally:
        client.close()
