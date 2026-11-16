"""ALTCHA proof-of-work against vectors recorded from the official widget."""

import base64
import hashlib
import json
import struct
import sys
import types

import pytest

from sigaa import altcha
from sigaa.altcha import (
    BACKEND_ENV,
    MAX_COST,
    MAX_KEY_LENGTH,
    Challenge,
    Solution,
    form_field_value,
    parse_challenge,
    solve,
    solve_challenge,
)
from sigaa.errors import STAGE_AUTH, CaptchaError, error_stage

# A real challenge as served by /sigaa/gerarDesafioCaptcha (public endpoint data,
# expired; session ids of the capture were never part of it). The tool never
# posted a solution for it: playground vectors below carry the recorded answers.
SIGAA_CHALLENGE = json.loads(
    '{"parameters":{"algorithm":"PBKDF2/SHA-256","cost":5000,"expiresAt":1794830960,'
    '"keyLength":32,"keyPrefix":"00","nonce":"f3903dcbb0b2a2d5643cb2d1deeb718d",'
    '"salt":"d5965c8037867402a56ef4a9e3b0a238"},'
    '"signature":"8f6594573c2bf3f67f46d6f9f6b86c7107541a425671a8b6884e2164b2000629"}'
)

# Recorded widget output for this challenge from playground.altcha.org: the
# browser solved it at counter 377 with exactly this derived key.
PLAYGROUND_NONCE = "def62607ef45c3c00a49817fffeb3f03"
PLAYGROUND_SALT = "9eef6216b095a7d52c421e64a2143baf"
PLAYGROUND_COUNTER = 377
PLAYGROUND_KEY = "009357f88ba40f5121a622711de129e181a922d34091644bc6cb2906ef0eeab7"


def derive(nonce_hex, salt_hex, counter, cost, length=32):
    password = bytes.fromhex(nonce_hex) + struct.pack(">I", counter)
    return hashlib.pbkdf2_hmac("sha256", password, bytes.fromhex(salt_hex), cost, length).hex()


def playground_challenge():
    return Challenge(
        algorithm="PBKDF2/SHA-256",
        cost=5000,
        key_length=32,
        key_prefix="00",
        nonce=PLAYGROUND_NONCE,
        salt=PLAYGROUND_SALT,
        signature="25f23f1b6cf746a212bcf1ee73ddb64f13c6c3b0b5fd7bc0f7bc71d0b06129da",
        parameters={
            "algorithm": "PBKDF2/SHA-256",
            "cost": 5000,
            "keyLength": 32,
            "keyPrefix": "00",
            "nonce": PLAYGROUND_NONCE,
            "salt": PLAYGROUND_SALT,
        },
    )


def test_solve_reproduces_the_widget_solution():
    solution = solve(playground_challenge())

    assert solution.counter == PLAYGROUND_COUNTER
    assert solution.derived_key == PLAYGROUND_KEY
    assert solution.derived_key == derive(PLAYGROUND_NONCE, PLAYGROUND_SALT, 377, 5000)


def test_deterministic_mode_finds_the_published_counter():
    # Server-picked counter 12: the prefix is half the key, so the answer is
    # unique and the solve must land on it exactly.
    nonce, salt = "3016cc87fed81d41d9f0dc767169159f", "d22ddfafba367c98c9d14b0f6a8d3ced"
    key = derive(nonce, salt, 12, 10)
    challenge = Challenge(
        "PBKDF2/SHA-256", 10, 32, key[:32], nonce, salt, "s" * 64, {"keyPrefix": key[:32]}
    )

    solution = solve(challenge)

    assert solution.counter == 12
    assert solution.derived_key == key


def test_parses_the_challenge_sigaa_serves():
    challenge = parse_challenge(json.dumps(SIGAA_CHALLENGE))

    assert challenge.algorithm == "PBKDF2/SHA-256"
    assert challenge.cost == 5000
    assert challenge.key_prefix == "00"
    assert challenge.key_length == 32
    assert challenge.parameters == SIGAA_CHALLENGE["parameters"]
    assert challenge.signature == SIGAA_CHALLENGE["signature"]


def test_payload_is_exactly_what_the_widget_posts():
    challenge = parse_challenge(json.dumps(SIGAA_CHALLENGE))
    solution = Solution(counter=123, derived_key="00ab", time_ms=128.8)

    field = form_field_value(challenge, solution)

    decoded = base64.b64decode(field, validate=True)
    assert decoded == json.dumps(
        {
            "challenge": {
                "parameters": SIGAA_CHALLENGE["parameters"],
                "signature": SIGAA_CHALLENGE["signature"],
            },
            "solution": {"counter": 123, "derivedKey": "00ab", "time": 128.8},
        },
        separators=(",", ":"),
    ).encode()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[1, 2]",
        '{"signature": "x"}',
        '{"parameters": {"algorithm": "PBKDF2/SHA-256", "cost": 1, "keyPrefix": "00",'
        ' "nonce": "ab", "salt": "cd"}}',
        '{"parameters": {"algorithm": "SHA-256", "cost": 1, "keyPrefix": "00",'
        ' "nonce": "ab", "salt": "cd"}, "signature": "x"}',
        '{"parameters": {"algorithm": "ARGON2ID", "cost": 1, "keyPrefix": "00",'
        ' "nonce": "ab", "salt": "cd"}, "signature": "x"}',
        '{"parameters": {"algorithm": "PBKDF2/SHA-256", "cost": 0, "keyPrefix": "00",'
        ' "nonce": "ab", "salt": "cd"}, "signature": "x"}',
        '{"parameters": {"algorithm": "PBKDF2/SHA-256", "cost": 1, "keyPrefix": "",'
        ' "nonce": "ab", "salt": "cd"}, "signature": "x"}',
        '{"parameters": {"algorithm": "PBKDF2/SHA-256", "cost": 1, "keyPrefix": "00",'
        ' "nonce": "nothex", "salt": "cd"}, "signature": "x"}',
        '{"parameters": {"algorithm": "PBKDF2/SHA-256", "cost": 1, "keyPrefix": "00",'
        ' "nonce": "ab", "salt": "cd", "keyLength": 0}, "signature": "x"}',
        '{"parameters": {"algorithm": "PBKDF2/SHA-256", "cost": 1, "keyPrefix": "00",'
        ' "nonce": "ab", "salt": "cd"}, "signature": ""}',
        '{"parameters": {"algorithm": "PBKDF2/SHA-256", "cost": true, "keyPrefix": "00",'
        ' "nonce": "ab", "salt": "cd"}, "signature": "x"}',
        '{"parameters": {"algorithm": "PBKDF2/SHA-256", "cost": 1, "keyPrefix": "00",'
        ' "nonce": "ab", "salt": "cd", "keyLength": true}, "signature": "x"}',
        '{"parameters": {"algorithm": "PBKDF2/SHA-256", "cost": %d, "keyPrefix": "00",'
        ' "nonce": "ab", "salt": "cd"}, "signature": "x"}' % (MAX_COST + 1),
        '{"parameters": {"algorithm": "PBKDF2/SHA-256", "cost": 1, "keyPrefix": "00",'
        ' "nonce": "ab", "salt": "cd", "keyLength": %d}, "signature": "x"}' % (MAX_KEY_LENGTH + 1),
    ],
)
def test_parse_refuses_what_it_cannot_answer(text):
    with pytest.raises(CaptchaError):
        parse_challenge(text)


def test_solve_gives_up_when_the_prefix_is_out_of_reach():
    challenge = Challenge(
        "PBKDF2/SHA-256", 10, 32, "00" * 16, "ab", "cd", "s" * 64, {}
    )

    with pytest.raises(CaptchaError, match="10 attempts"):
        solve(challenge, max_attempts=10)


def test_max_attempts_is_the_number_of_derivations(monkeypatch):
    derivations = []
    real = hashlib.pbkdf2_hmac

    def counting(*args):
        derivations.append(args[1])
        return real(*args)

    monkeypatch.setattr(altcha.hashlib, "pbkdf2_hmac", counting)
    challenge = Challenge("PBKDF2/SHA-256", 10, 32, "00" * 16, "ab", "cd", "s" * 64, {})

    with pytest.raises(CaptchaError):
        solve(challenge, max_attempts=10)

    assert len(derivations) == 10
    assert derivations[-1] == bytes.fromhex("ab") + struct.pack(">I", 9)


def test_parse_accepts_the_largest_cost_and_key_length():
    body = {
        "parameters": {
            "algorithm": "PBKDF2/SHA-512", "cost": MAX_COST, "keyLength": MAX_KEY_LENGTH,
            "keyPrefix": "00", "nonce": "ab", "salt": "cd",
        },
        "signature": "x",
    }

    challenge = parse_challenge(json.dumps(body))

    assert (challenge.cost, challenge.key_length) == (MAX_COST, MAX_KEY_LENGTH)


@pytest.mark.parametrize(
    ("time_ms", "posted"),
    [(128.84, "128.8"), (134.96, "135"), (0.5952499923296273, "0.6"), (135.0, "135")],
)
def test_solve_time_is_posted_with_one_decimal_like_the_widget(time_ms, posted):
    challenge = parse_challenge(json.dumps(SIGAA_CHALLENGE))

    field = form_field_value(challenge, Solution(counter=1, derived_key="00", time_ms=time_ms))

    assert base64.b64decode(field).decode().endswith(f'"time":{posted}}}}}')


def test_captcha_failures_are_staged_auth():
    assert error_stage(CaptchaError("unsolved")) == STAGE_AUTH


# --- backend selection (solve_challenge) -------------------------------------
#
# A quick CPU-solvable challenge: deterministic counter 12, cost 10.
EASY_CHALLENGE = Challenge(
    "PBKDF2/SHA-256", 10, 32, derive(
        "3016cc87fed81d41d9f0dc767169159f", "d22ddfafba367c98c9d14b0f6a8d3ced", 12, 10
    )[:32],
    "3016cc87fed81d41d9f0dc767169159f", "d22ddfafba367c98c9d14b0f6a8d3ced",
    "s" * 64, {},
)


class _StubMetal(types.ModuleType):
    """A sigaa.altcha_metal stand-in for dispatch tests, without Metal."""

    MetalUnavailable = type("MetalUnavailable", (RuntimeError,), {})

    def __init__(self, *, fail=False, error=None):
        super().__init__("sigaa.altcha_metal")
        self.error = error or (self.MetalUnavailable("no device") if fail else None)
        self.calls = []

    def solve(self, challenge, **kwargs):
        self.calls.append(challenge)
        if self.error is not None:
            raise self.error
        return Solution(counter=1, derived_key="00ff", time_ms=1.0)


def test_auto_backend_uses_metal_when_it_works(monkeypatch):
    stub = _StubMetal()
    monkeypatch.setitem(sys.modules, "sigaa.altcha_metal", stub)

    solution = solve_challenge(EASY_CHALLENGE)

    assert stub.calls == [EASY_CHALLENGE]
    assert solution.counter == 1


def test_auto_backend_falls_back_to_cpu_when_metal_is_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "sigaa.altcha_metal", None)  # extra not installed

    assert solve_challenge(EASY_CHALLENGE).counter == 12


def test_auto_backend_falls_back_to_cpu_when_metal_fails(monkeypatch):
    monkeypatch.setitem(sys.modules, "sigaa.altcha_metal", _StubMetal(fail=True))

    assert solve_challenge(EASY_CHALLENGE).counter == 12


def test_forced_metal_never_falls_back(monkeypatch):
    monkeypatch.setenv(BACKEND_ENV, "metal")
    monkeypatch.setitem(sys.modules, "sigaa.altcha_metal", _StubMetal(fail=True))

    with pytest.raises(CaptchaError, match="Metal backend requested"):
        solve_challenge(EASY_CHALLENGE)


def test_cpu_backend_never_imports_metal(monkeypatch):
    stub = _StubMetal()

    def boom(*args, **kwargs):
        raise AssertionError("CPU backend must not touch the Metal module")

    stub.solve = boom
    monkeypatch.setenv(BACKEND_ENV, "cpu")
    monkeypatch.setitem(sys.modules, "sigaa.altcha_metal", stub)

    assert solve_challenge(EASY_CHALLENGE).counter == 12
    assert stub.calls == []


def test_unknown_backend_value_is_refused(monkeypatch):
    monkeypatch.setenv(BACKEND_ENV, "gpu")

    with pytest.raises(CaptchaError, match=BACKEND_ENV):
        solve_challenge(EASY_CHALLENGE)


# Whatever the GPU path raises, a login must not fail on it: pyobjc and driver
# errors, and input the kernel's packing rejects, are not MetalUnavailable.
UNEXPECTED_METAL_ERRORS = [ValueError("non-hexadecimal"), struct.error("out of range"), OSError()]


@pytest.mark.parametrize("error", UNEXPECTED_METAL_ERRORS, ids=lambda e: type(e).__name__)
def test_auto_backend_falls_back_to_cpu_on_any_metal_error(monkeypatch, error):
    monkeypatch.setitem(sys.modules, "sigaa.altcha_metal", _StubMetal(error=error))

    assert solve_challenge(EASY_CHALLENGE).counter == 12


@pytest.mark.parametrize("error", UNEXPECTED_METAL_ERRORS, ids=lambda e: type(e).__name__)
def test_forced_metal_reports_any_metal_error_as_a_captcha_failure(monkeypatch, error):
    monkeypatch.setenv(BACKEND_ENV, "metal")
    monkeypatch.setitem(sys.modules, "sigaa.altcha_metal", _StubMetal(error=error))

    with pytest.raises(CaptchaError, match="Metal backend requested"):
        solve_challenge(EASY_CHALLENGE)


def test_metal_giving_up_is_not_retried_on_the_cpu(monkeypatch):
    stub = _StubMetal(error=CaptchaError("ALTCHA not solved after 5 attempts"))
    monkeypatch.setitem(sys.modules, "sigaa.altcha_metal", stub)

    def cpu(*args, **kwargs):
        raise AssertionError("the bounds were reached; the CPU must not search again")

    monkeypatch.setattr(altcha, "solve", cpu)

    with pytest.raises(CaptchaError, match="5 attempts"):
        solve_challenge(EASY_CHALLENGE)


def test_cpu_fallback_gets_only_the_time_metal_left(monkeypatch):
    clock = iter([100.0, 130.0])
    monkeypatch.setattr(altcha.time, "monotonic", lambda: next(clock))
    monkeypatch.setitem(sys.modules, "sigaa.altcha_metal", _StubMetal(fail=True))
    seen = {}

    def cpu(challenge, *, max_attempts, timeout_seconds):
        seen.update(max_attempts=max_attempts, timeout_seconds=timeout_seconds)
        return Solution(counter=12, derived_key="00", time_ms=1.0)

    monkeypatch.setattr(altcha, "solve", cpu)

    solve_challenge(EASY_CHALLENGE, max_attempts=50, timeout_seconds=90.0)

    assert seen == {"max_attempts": 50, "timeout_seconds": 60.0}
