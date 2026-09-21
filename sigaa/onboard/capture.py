"""Capture actual response bodies without submitting academic changes."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl

from bs4 import BeautifulSoup

from ..client import SigaaClient
from ..errors import SigaaError
from .features import FEATURES, CaptureUnavailable

_BLOCKED = re.compile(
    r"confirmar|enviar|cadastrar|submeter|botaoSubmissao|btaoSelecionarTurmas", re.I
)


class ReadOnlyViolation(SigaaError):
    """A capture request attempted to submit a state-changing control."""


class ReadOnlySession:
    """Wrap a Session and guard the transport too, including navigator calls.

    Only registry fetchers are dispatched by capture. The additional guard runs
    before each HTTP POST, even if a provider accesses its raw client directly.
    ``last_response`` holds only the most recent non-redirect response, which
    capture reads right after each fetcher returns.
    """

    def __init__(self, session):
        self._wrapped = session
        self.last_response = None
        session._client.event_hooks.setdefault("request", []).append(self._guard_request)
        session._client.event_hooks.setdefault("response", []).append(self._record)

    def __getattr__(self, name):
        return getattr(self._wrapped, name)

    @staticmethod
    def validate_post(data):
        for key, value in data.items():
            values = value if isinstance(value, (list, tuple)) else [value]
            if _BLOCKED.search(str(key)) or any(_BLOCKED.search(str(v)) for v in values):
                raise ReadOnlyViolation("capture refused a submission control")

    def _guard_request(self, request):
        if request.method in {"GET", "HEAD"}:
            return
        if request.method != "POST":
            raise ReadOnlyViolation("capture refused a non-navigation HTTP method")
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("application/x-www-form-urlencoded"):
            raise ReadOnlyViolation("capture only allows URL-encoded navigation forms")
        for key, value in parse_qsl(request.content.decode("utf-8"), keep_blank_values=True):
            self.validate_post({key: value})

    def _record(self, response):
        response.read()
        if not response.is_redirect:
            self.last_response = response

    def post(self, url, data):
        self.validate_post(data)
        return self._wrapped.post(url, data)


def private_directory(path: Path):
    """Create each missing directory privately; reject symlinks in the path."""
    path = path.absolute()
    for parent in [*reversed(path.parents), path]:
        if parent.is_symlink():
            raise ValueError("capture path cannot contain symlinks")
        if not parent.exists():
            parent.mkdir(mode=0o700)
    path.chmod(0o700)


def private_write(path: Path, content: bytes):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(content)


def safe_url(url):
    parsed = urlsplit(str(url))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.split(";")[0], "", ""))


def sigaa_version(text):
    soup = BeautifulSoup(text, "lxml")
    footer = soup.select_one("#rodape, #footer, footer")
    match = re.search(r"(?:v|vers[aã]o\s*)([0-9]+(?:\.[0-9]+)+(?:[-.][a-zA-Z0-9]+)*)",
                      footer.get_text(" ", strip=True) if footer else "", re.I)
    return match.group(1) if match else None


def capture(settings, *, output: Path = Path("captures"), include_matricula=False):
    username, password = settings.require_credentials()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S.%fZ")
    directory = output / settings.institution / stamp
    private_directory(directory)
    manifest = {"institution": settings.institution, "captured_at": stamp, "entries": []}
    identity = {"username": username}
    with SigaaClient(username, password, institution=settings.institution) as client:
        recorder = ReadOnlySession(client._session)
        client._session = recorder
        client._portal()
        try:
            student = client.get_student()
            identity.update({k: getattr(student, k, None) for k in ("name", "matricula", "email")})
        except Exception:
            # Keep the private portal even when a new fork cannot identify the student.
            pass
        private_write(directory / "identity.json", json.dumps(identity).encode())
        try:
            turmas = client.list_turmas()[:2]
        except Exception:
            turmas = []
        for feature in FEATURES:
            contexts = turmas if feature.needs_turma else [None]
            if not contexts:
                manifest["entries"].append({"feature": feature.key, "status": "not_captured"})
            for turma in contexts:
                entry = {
                    "feature": feature.key,
                    "turma_id": turma.id_turma if turma else None,
                    "source_action": feature.key,
                }
                manifest["entries"].append(entry)
                if feature.capability not in client.profile.capabilities:
                    entry["status"] = "unsupported"
                    continue
                if feature.opt_in and not include_matricula:
                    entry["status"] = "not_captured"
                    continue
                try:
                    html = feature.fetcher(client, turma)
                    response = recorder.last_response
                    # A fetcher that served cached HTML or parsed an extra page
                    # last has no raw response of its own to save.
                    if response is None or response.text != html:
                        raise CaptureUnavailable("raw HTTP response unavailable")
                    filename = f"{len(manifest['entries']):02d}-{feature.key}.body"
                    private_write(directory / filename, response.content)
                    entry.update({
                        "status": "captured",
                        "file": filename,
                        "method": response.request.method,
                        "http_status": response.status_code,
                        "content_type": response.headers.get("content-type", ""),
                        "encoding": response.encoding,
                        "final_url": safe_url(response.url),
                        "sha256": hashlib.sha256(response.content).hexdigest(),
                        "sigaa_version": sigaa_version(response.text),
                    })
                except CaptureUnavailable as exc:
                    entry.update({"status": "not_captured", "error_type": type(exc).__name__})
                except Exception as exc:
                    entry.update({"status": "nav_failed", "error_type": type(exc).__name__})
    private_write(directory / "manifest.json", json.dumps(manifest, indent=2).encode())
    return directory, manifest
