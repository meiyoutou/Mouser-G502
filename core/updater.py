"""Notify-only update checks for GitHub Releases."""

from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from core.version import APP_VERSION


DEFAULT_RELEASE_REPO = "TomBadash/Mouser"
_GITHUB_API = "https://api.github.com/repos/{repo}/releases/latest"
_LATEST_RELEASE_URL_ENV = "MOUSER_UPDATE_LATEST_RELEASE_URL"
_USER_AGENT = f"Mouser/{APP_VERSION}"
DEFAULT_AUTO_CHECK_INTERVAL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class LatestRelease:
    tag_name: str
    html_url: str
    name: str = ""
    published_at: str = ""


@dataclass(frozen=True)
class UpdateCheckState:
    last_check: float = 0.0
    etag: str = ""
    last_modified: str = ""
    backoff_until: float = 0.0
    last_seen_latest_version: str = ""
    skipped_version: str = ""
    highest_trusted_build: int = 0

    @classmethod
    def from_dict(cls, data) -> "UpdateCheckState":
        if not isinstance(data, dict):
            return cls()

        def number(name):
            try:
                return float(data.get(name) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        return cls(
            last_check=number("last_check"),
            etag=str(data.get("etag") or ""),
            last_modified=str(data.get("last_modified") or ""),
            backoff_until=number("backoff_until"),
            last_seen_latest_version=str(data.get("last_seen_latest_version") or ""),
            skipped_version=str(data.get("skipped_version") or ""),
            highest_trusted_build=int(number("highest_trusted_build")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "last_check": self.last_check,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "backoff_until": self.backoff_until,
            "last_seen_latest_version": self.last_seen_latest_version,
            "skipped_version": self.skipped_version,
            "highest_trusted_build": self.highest_trusted_build,
        }


@dataclass(frozen=True)
class UpdateCheckResult:
    release: LatestRelease | None
    state: UpdateCheckState
    reachable: bool
    not_modified: bool = False
    throttled: bool = False
    rate_limited: bool = False


def _normalized_stable_parts(version: str) -> tuple[int, ...] | None:
    value = (version or "").strip()
    if value.startswith("v"):
        value = value[1:]
    if not value or "-" in value:
        return None
    match = re.fullmatch(r"\d+(?:\.\d+)*", value)
    if not match:
        return None
    return tuple(int(part) for part in value.split("."))


def _padded(parts: tuple[int, ...], length: int) -> tuple[int, ...]:
    return parts + (0,) * max(0, length - len(parts))


def is_newer(current: str, latest: str) -> bool:
    """Return True when latest is a newer stable semver-ish version."""
    current_parts = _normalized_stable_parts(current)
    latest_parts = _normalized_stable_parts(latest)
    if current_parts is None or latest_parts is None:
        return False
    length = max(len(current_parts), len(latest_parts))
    return _padded(latest_parts, length) > _padded(current_parts, length)


def _headers_value(headers, name: str) -> str:
    getter = getattr(headers, "get", None)
    if getter is None:
        return ""
    return str(getter(name) or "")


def _retry_after_until(headers, now: float) -> float:
    retry_after = _headers_value(headers, "Retry-After")
    if retry_after:
        try:
            return now + max(0, int(retry_after))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(retry_after)
                return max(now, parsed.timestamp())
            except (TypeError, ValueError, OSError):
                pass
    reset = _headers_value(headers, "X-RateLimit-Reset")
    if reset:
        try:
            return max(now, float(reset))
        except ValueError:
            pass
    return now


def _latest_release_url(repo: str) -> str:
    override = os.environ.get(_LATEST_RELEASE_URL_ENV, "").strip()
    if override:
        return override
    return _GITHUB_API.format(repo=repo)


def _request(repo: str, state: UpdateCheckState) -> urllib.request.Request:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
    }
    if state.etag:
        headers["If-None-Match"] = state.etag
    if state.last_modified:
        headers["If-Modified-Since"] = state.last_modified
    return urllib.request.Request(_latest_release_url(repo), headers=headers)


def _read_json_response(response):
    return json.loads(response.read().decode("utf-8-sig"))


def _state_after_attempt(state: UpdateCheckState, now: float, **updates) -> UpdateCheckState:
    return UpdateCheckState(**{**state.to_dict(), "last_check": now, **updates})


def _parse_release(payload) -> LatestRelease | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("draft") or payload.get("prerelease"):
        return None
    tag_name = str(payload.get("tag_name") or "").strip()
    html_url = str(payload.get("html_url") or "").strip()
    if not tag_name or not html_url:
        return None
    return LatestRelease(
        tag_name=tag_name,
        html_url=html_url,
        name=str(payload.get("name") or ""),
        published_at=str(payload.get("published_at") or ""),
    )


def check_latest_release(
    repo: str = DEFAULT_RELEASE_REPO,
    timeout: float = 5.0,
    *,
    state: UpdateCheckState | None = None,
    now: float | None = None,
    manual: bool = False,
    min_interval_seconds: int = DEFAULT_AUTO_CHECK_INTERVAL_SECONDS,
) -> UpdateCheckResult:
    """Fetch latest-release metadata while respecting cache/backoff state."""
    repo = (repo or "").strip()
    state = state or UpdateCheckState()
    now = time.time() if now is None else float(now)
    if not repo or "/" not in repo:
        return UpdateCheckResult(None, state, reachable=False)
    if state.backoff_until and now < state.backoff_until:
        return UpdateCheckResult(
            None, state, reachable=False, throttled=True, rate_limited=True
        )
    if (
        not manual
        and state.last_check
        and now - state.last_check < max(0, min_interval_seconds)
    ):
        return UpdateCheckResult(None, state, reachable=True, throttled=True)

    request = _request(repo, state)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            headers = getattr(response, "headers", {})
            if status == 304:
                return UpdateCheckResult(
                    None,
                    UpdateCheckState(
                        **{
                            **state.to_dict(),
                            "last_check": now,
                        }
                    ),
                    reachable=True,
                    not_modified=True,
                )
            if status >= 400:
                backoff = _retry_after_until(headers, now)
                return UpdateCheckResult(
                    None,
                    UpdateCheckState(
                        **{
                            **state.to_dict(),
                            "last_check": now,
                            "backoff_until": backoff,
                        }
                    ),
                    reachable=False,
                    rate_limited=bool(backoff > now),
                )
            try:
                payload = _read_json_response(response)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                print(
                    f"[update] release metadata could not be read: {exc}",
                    file=sys.stderr,
                )
                return UpdateCheckResult(
                    None,
                    _state_after_attempt(state, now),
                    reachable=False,
                )
            release = _parse_release(payload)
            next_state = _state_after_attempt(
                state,
                now,
                etag=_headers_value(headers, "ETag") or state.etag,
                last_modified=(
                    _headers_value(headers, "Last-Modified")
                    or state.last_modified
                ),
                backoff_until=0.0,
            )
            if release is None:
                return UpdateCheckResult(None, next_state, reachable=False)
            next_state = _state_after_attempt(
                next_state,
                now,
                last_seen_latest_version=release.tag_name,
            )
            return UpdateCheckResult(release, next_state, reachable=True)
    except urllib.error.HTTPError as exc:
        headers = getattr(exc, "headers", {})
        if exc.code == 304:
            return UpdateCheckResult(
                None,
                UpdateCheckState(**{**state.to_dict(), "last_check": now}),
                reachable=True,
                not_modified=True,
            )
        backoff = _retry_after_until(headers, now)
        return UpdateCheckResult(
            None,
            UpdateCheckState(
                **{
                    **state.to_dict(),
                    "last_check": now,
                    "backoff_until": backoff,
                }
            ),
            reachable=False,
            rate_limited=bool(backoff > now),
        )
    except (
        OSError,
        TimeoutError,
        urllib.error.URLError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return UpdateCheckResult(
            None,
            _state_after_attempt(state, now),
            reachable=False,
        )


def fetch_latest_release(
    repo: str = DEFAULT_RELEASE_REPO,
    timeout: float = 5.0,
) -> LatestRelease | None:
    """Fetch the latest GitHub Release metadata.

    This is deliberately notify-only: it fetches release metadata but never
    downloads release assets.
    """
    return check_latest_release(repo, timeout, manual=True).release
