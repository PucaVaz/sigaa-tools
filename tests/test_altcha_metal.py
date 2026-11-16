"""Metal GPU backend, live on machines with a Metal device (skipped elsewhere).

CI has no Metal; these tests only assert what the study verified and what the
self-check already guarantees at runtime: the GPU reproduces the CPU's keys
and lands on the same counters the widget and the CPU solver find.
"""

import hashlib
import json
import secrets
import struct
import threading

import pytest

from sigaa import altcha, altcha_metal
from sigaa.altcha import BACKEND_ENV, Challenge, parse_challenge, solve_challenge
from sigaa.errors import CaptchaError

pytestmark = pytest.mark.skipif(
    not altcha_metal.available(), reason="no Metal device on this machine"
)

# Public playground challenge whose recorded widget answer is counter 377.
PLAYGROUND = json.dumps(
    {
        "parameters": {
            "algorithm": "PBKDF2/SHA-256",
            "cost": 5000,
            "keyLength": 32,
            "keyPrefix": "00",
            "nonce": "def62607ef45c3c00a49817fffeb3f03",
            "salt": "9eef6216b095a7d52c421e64a2143baf",
        },
        "signature": "5e3ff246feae497ec9cef9333aebe55ac1c076625a73b5c032b737f2aa347a9d",
    }
)

NONCE = "3016cc87fed81d41d9f0dc767169159f"
SALT = "d22ddfafba367c98c9d14b0f6a8d3ced"


def derive(challenge, counter):
    """The CPU reference: the same key derivation, one run, from hashlib."""
    password = bytes.fromhex(challenge.nonce) + struct.pack(">I", counter)
    return hashlib.pbkdf2_hmac(
        "sha256", password, bytes.fromhex(challenge.salt), challenge.cost, 32
    ).hex()


def test_metal_reproduces_the_widget_solution():
    solution = altcha_metal.solve(parse_challenge(PLAYGROUND))

    assert solution.counter == 377
    assert solution.derived_key.startswith("00")


def test_metal_keys_match_hashlib():
    challenge = parse_challenge(PLAYGROUND)
    solution = altcha_metal.solve(challenge)

    assert solution.derived_key == derive(challenge, solution.counter)


def test_metal_solves_the_deterministic_mode():
    key = hashlib.pbkdf2_hmac(
        "sha256",
        bytes.fromhex(NONCE) + struct.pack(">I", 12),
        bytes.fromhex(SALT),
        10,
        32,
    ).hex()
    challenge = parse_challenge(
        json.dumps(
            {
                "parameters": {
                    "algorithm": "PBKDF2/SHA-256",
                    "cost": 10,
                    "keyLength": 32,
                    "keyPrefix": key[:32],
                    "nonce": NONCE,
                    "salt": SALT,
                },
                "signature": "s" * 64,
            }
        )
    )

    assert altcha_metal.solve(challenge).counter == 12


def test_solve_challenge_goes_through_the_gpu():
    # auto picks Metal when it is available; the answer must be identical to
    # the CPU solver's either way.
    challenge = parse_challenge(PLAYGROUND)
    solution = solve_challenge(challenge)

    assert solution.counter == 377
    assert solution.derived_key == derive(challenge, 377)


def _challenge(prefix, *, cost=10, nonce=NONCE, salt=SALT):
    return Challenge("PBKDF2/SHA-256", cost, 32, prefix, nonce, salt, "s" * 64, {})


@pytest.mark.parametrize("prefix", ["0", "000", "zz", "00" * 17])
def test_prefix_the_kernel_cannot_compare_is_left_to_the_cpu(prefix):
    with pytest.raises(altcha_metal.MetalUnavailable):
        altcha_metal.solve(_challenge(prefix), max_attempts=20)


@pytest.mark.parametrize("prefix", ["0", "000"])
def test_odd_length_prefix_is_solved_like_the_cpu_solves_it(prefix):
    # The widget compares hex text, so a half-byte prefix is a valid challenge.
    challenge = _challenge(prefix)

    solution = solve_challenge(challenge)

    cpu = altcha.solve(challenge)
    assert (solution.counter, solution.derived_key) == (cpu.counter, cpu.derived_key)


def test_forced_metal_refuses_a_prefix_only_the_cpu_can_compare(monkeypatch):
    monkeypatch.setenv(BACKEND_ENV, "metal")

    with pytest.raises(CaptchaError, match="Metal backend requested"):
        solve_challenge(_challenge("0"))


def _solver():
    altcha_metal.solve(_challenge("00"))  # builds and self-checks the singleton
    return altcha_metal._STATE[1]


def test_key_from_another_dispatch_is_refused_then_solved_on_the_cpu(monkeypatch):
    # A foreign key that also starts with the prefix used to pass the only check.
    challenge = _challenge("00")
    foreign = derive(_challenge("00", nonce=secrets.token_hex(16)), 0)
    foreign = "00" + foreign[2:]
    monkeypatch.setattr(_solver(), "_run_batch", lambda *args: (0, foreign))

    with pytest.raises(altcha_metal.MetalUnavailable, match="disagrees with hashlib"):
        altcha_metal.solve(challenge)

    solution = solve_challenge(challenge)
    assert solution.derived_key == derive(challenge, solution.counter)
    assert solution.counter == altcha.solve(challenge).counter


def test_concurrent_solves_each_get_their_own_key():
    wrong = []

    def worker():
        for _ in range(20):
            challenge = _challenge(
                "00", cost=50, nonce=secrets.token_hex(16), salt=secrets.token_hex(16)
            )
            solution = altcha_metal.solve(challenge)
            if solution.derived_key != derive(challenge, solution.counter):
                wrong.append(solution.counter)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert wrong == []


def test_give_up_bounds_match_the_cpu_solver():
    unreachable = _challenge("00" * 16)

    with pytest.raises(CaptchaError, match="after 10 attempts"):
        altcha_metal.solve(unreachable, max_attempts=10)
    with pytest.raises(CaptchaError, match="after 10 attempts"):
        altcha.solve(unreachable, max_attempts=10)


def test_cost_that_would_hold_the_gpu_too_long_is_left_to_the_cpu():
    # A dispatch cannot be interrupted and lasts one whole derivation.
    with pytest.raises(altcha_metal.MetalUnavailable, match="cost"):
        altcha_metal.solve(_challenge("00", cost=altcha_metal._MAX_COST + 1))
