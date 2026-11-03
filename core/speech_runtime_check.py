"""Explicit, non-recording dependency check through the optional local helper."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def run_check(report_path):
    from core.version import APP_VERSION
    from core.speech_client import SpeechClient
    from core.speech_models import runtime_enabled, catalog_status
    report = {"version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
              "microphone_opened": False, "input_sent": False, "checks": {}}
    if not runtime_enabled():
        report["checks"]["optional_speech_not_installed"] = {"ok": True, "speech_enabled": False}
        report["ok"] = True
    else:
        client = SpeechClient()
        try:
            result = client.query("check", timeout=60)
            report["checks"]["independent_speech_runtime"] = result
            report["models"] = [{"id": item["id"], "installed": item["installed"],
                                 "vad_installed": item["vad_installed"]} for item in catalog_status()]
            report["ok"] = result.get("ok") is True
        except Exception as error:
            report["checks"]["independent_speech_runtime"] = {"ok": False, "error": str(error)}
            report["ok"] = False
        finally:
            client.close()
    Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
