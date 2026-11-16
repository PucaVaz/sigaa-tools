"""ALTCHA proof-of-work (v2): solve SIGAA's login captcha without a browser.

The login form embeds ``<altcha-widget challenge="...">`` (official widget
3.5.0, byte-identical to the upstream npm release). The widget fetches a signed
challenge, brute-forces a counter until PBKDF2(nonce‖counter, salt, cost) starts
with the challenge's ``keyPrefix``, and posts a base64 payload in a hidden form
field. This module is the widget's solver in Python, so the login flow can post
the password unattended again.

Encoding and payload shape were checked against the official widget's source and
reproduced from playground.altcha.org vectors (see ``tests/test_altcha.py``):

- the counter is appended to the hex-decoded nonce as a big-endian uint32;
- the posted field is base64 JSON of ``{"challenge": {"parameters": ...,
  "signature": ...}, "solution": {...}}`` with ``parameters`` echoed verbatim.

Only the PBKDF2 algorithms the widget supports natively are implemented; the
memory-hard ones (Scrypt, Argon2id) raise ``CaptchaError``. Challenge expiry is
left to the server: the challenge is fetched, solved and posted within seconds,
and a local clock off by minutes must not refuse a valid challenge.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import time
from dataclasses import dataclass
from typing import Any

from .errors import CaptchaError

# The widget encodes the counter as a uint32; this is its hard ceiling.
MAX_COUNTER = 0xFFFFFFFF

# One derivation cannot be interrupted, so the timeout is only as responsive as
# a single attempt. 10M iterations is about a second of native PBKDF2 (2000x
# SIGAA's cost of 5000); a challenge above it is refused instead of hanging an
# unattended run. 64 bytes is the longest digest the widget's algorithms emit.
MAX_COST = 10_000_000
MAX_KEY_LENGTH = 64

# Give-up bounds. SIGAA's current setting (prefix "00") needs ~256 attempts on
# average; a full second of native PBKDF2 covers a difficulty raise by ~400x.
MAX_ATTEMPTS = 100_000
TIMEOUT_SECONDS = 90.0

# The PBKDF2 variants the widget implements with native WebCrypto. hashlib takes
# the same names minus the dash ("PBKDF2/SHA-256" -> "sha256").
_PBKDF2_ALGORITHMS = {"PBKDF2/SHA-256", "PBKDF2/SHA-384", "PBKDF2/SHA-512"}


@dataclass(frozen=True)
class Challenge:
    """A signed challenge as served; ``parameters`` is echoed verbatim."""

    algorithm: str
    cost: int
    key_length: int
    key_prefix: str
    nonce: str
    salt: str
    signature: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class Solution:
    counter: int
    # Hex of the derived key, the form the widget posts.
    derived_key: str
    time_ms: float


def parse_challenge(text: str) -> Challenge:
    """Parse the challenge endpoint's JSON body, refusing anything else.

    The v2 format is ``{"parameters": {...}, "signature": "..."}``. The v1 flat
    format (``algorithm``/``salt``/``challenge`` at the top level) is a
    different, incompatible protocol and is rejected here.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise CaptchaError("ALTCHA challenge is not JSON") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("parameters"), dict):
        raise CaptchaError("ALTCHA challenge has no parameters object")
    if not isinstance(payload.get("signature"), str) or not payload["signature"]:
        raise CaptchaError("ALTCHA challenge has no signature")
    parameters = payload["parameters"]
    algorithm = _required(parameters, "algorithm", str)
    if algorithm not in _PBKDF2_ALGORITHMS:
        raise CaptchaError(f"unsupported ALTCHA algorithm: {algorithm}")
    cost = _required(parameters, "cost", int)
    if not 1 <= cost <= MAX_COST:
        raise CaptchaError(f"ALTCHA cost must be between 1 and {MAX_COST}, got {cost}")
    nonce = _required(parameters, "nonce", str)
    salt = _required(parameters, "salt", str)
    key_prefix = _required(parameters, "keyPrefix", str)
    if not key_prefix:
        raise CaptchaError("ALTCHA keyPrefix is empty")
    key_length = parameters.get("keyLength", 32)
    if not _is_integer(key_length) or not 1 <= key_length <= MAX_KEY_LENGTH:
        raise CaptchaError(
            f"ALTCHA keyLength must be an integer between 1 and {MAX_KEY_LENGTH}, "
            f"got {key_length!r}"
        )
    if len(key_prefix) > key_length * 2:
        raise CaptchaError("ALTCHA keyPrefix is longer than the key")
    _hex_bytes(nonce, "nonce")
    _hex_bytes(salt, "salt")
    return Challenge(
        algorithm=algorithm,
        cost=cost,
        key_length=key_length,
        key_prefix=key_prefix,
        nonce=nonce,
        salt=salt,
        signature=payload["signature"],
        parameters=parameters,
    )


def solve(
    challenge: Challenge,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    timeout_seconds: float = TIMEOUT_SECONDS,
) -> Solution:
    """Brute-force the counter, starting at 0 like the widget does.

    ``max_attempts`` is the number of derivations: counters 0..max_attempts-1.
    """
    prefix = challenge.key_prefix.lower()
    nonce = _hex_bytes(challenge.nonce, "nonce")
    salt = _hex_bytes(challenge.salt, "salt")
    hash_name = challenge.algorithm.removeprefix("PBKDF2/").replace("-", "").lower()
    started = time.monotonic()
    for counter in range(min(max_attempts, MAX_COUNTER + 1)):
        derived = hashlib.pbkdf2_hmac(
            hash_name,
            nonce + struct.pack(">I", counter),
            salt,
            challenge.cost,
            challenge.key_length,
        ).hex()
        if derived.startswith(prefix):
            return Solution(counter, derived, (time.monotonic() - started) * 1000)
        if time.monotonic() - started > timeout_seconds:
            raise CaptchaError(
                f"ALTCHA not solved within {timeout_seconds:g}s "
                f"({counter + 1} attempts, prefix {prefix!r})"
            )
    raise CaptchaError(
        f"ALTCHA not solved after {max_attempts} attempts (prefix {prefix!r})"
    )


def form_field_value(challenge: Challenge, solution: Solution) -> str:
    """The base64 payload the widget puts in its hidden form field."""
    payload = {
        "challenge": {
            "parameters": challenge.parameters,
            "signature": challenge.signature,
        },
        "solution": {
            "counter": solution.counter,
            "derivedKey": solution.derived_key,
            "time": _widget_time(solution.time_ms),
        },
    }
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    return base64.b64encode(encoded).decode()


def _widget_time(time_ms: float) -> int | float:
    """Solve time as the widget posts it: one decimal, and JSON-serialized the
    way JavaScript does (a whole number has no fractional part)."""
    rounded = round(time_ms, 1)
    return int(rounded) if rounded.is_integer() else rounded


def _is_integer(value: Any) -> bool:
    # JSON true/false are ints to isinstance; they are not a cost or a length.
    return isinstance(value, int) and not isinstance(value, bool)


def _required(parameters: dict, key: str, kind: type) -> Any:
    value = parameters.get(key)
    valid = _is_integer(value) if kind is int else isinstance(value, kind)
    if not valid or (kind is str and not value):
        raise CaptchaError(f"ALTCHA challenge parameter {key!r} is missing")
    return value


def _hex_bytes(value: str, name: str) -> bytes:
    try:
        return bytes.fromhex(value)
    except ValueError:
        raise CaptchaError(f"ALTCHA challenge {name} is not hexadecimal") from None
