"""HTTP with the standard library: JSON requests and checked downloads."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .config import USER_AGENT

TIMEOUT = 30


class HttpError(Exception):
    def __init__(self, status: int, body: Any, url: str):
        super().__init__(f"{urllib.parse.urlsplit(url).netloc} answered {status}")
        self.status = status
        self.body = body


def _request(url: str, data: bytes | None, headers: dict[str, str], method: str | None) -> urllib.request.Request:
    return urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **headers}, method=method)


def request_json(
    url: str,
    *,
    json_body: Any = None,
    form: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    method: str | None = None,
) -> tuple[int, Any]:
    """(status, parsed JSON or None). Error statuses are returned, not raised; no connection raises OSError."""
    hdrs = {"Accept": "application/json", **(headers or {})}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        hdrs["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        with urllib.request.urlopen(_request(url, data, hdrs, method), timeout=TIMEOUT) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None


def get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    status, body = request_json(url, headers=headers)
    if status != 200:
        raise HttpError(status, body, url)
    return body


def get_bytes(url: str) -> bytes:
    try:
        with urllib.request.urlopen(_request(url, None, {}, None), timeout=TIMEOUT) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, None, url) from None


def file_digest(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(
    url: str,
    dest: Path,
    *,
    sha1: str | None = None,
    sha256: str | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """Downloads `url` to `dest` through a temporary file, and keeps it only if its digest is the one given."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    algorithm, expected = ("sha256", sha256) if sha256 else ("sha1", sha1)
    h = hashlib.new(algorithm)
    try:
        with urllib.request.urlopen(_request(url, None, {}, None), timeout=TIMEOUT) as r, open(tmp, "wb") as out:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            for chunk in iter(lambda: r.read(1 << 16), b""):
                out.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        raise HttpError(e.code, None, url) from None
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if expected and h.hexdigest() != expected.lower():
        tmp.unlink(missing_ok=True)
        raise ValueError(f"{dest.name}: the download doesn't match its {algorithm} ({url})")
    os.replace(tmp, dest)
