"""Metal GPU backend, live on machines with a Metal device (skipped elsewhere).

CI has no Metal; these tests only assert what the study verified and what the
self-check already guarantees at runtime: the GPU reproduces the CPU's keys
and lands on the same counters the widget and the CPU solver find.
"""

import hashlib
import json
import struct

import pytest

from sigaa import altcha_metal
from sigaa.altcha import parse_challenge, solve_challenge

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
