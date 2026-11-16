"""ALTCHA proof-of-work against vectors recorded from the official widget."""

import base64
import hashlib
import json
import struct

import pytest

from sigaa.altcha import Challenge, Solution, form_field_value, parse_challenge, solve
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


def test_captcha_failures_are_staged_auth():
    assert error_stage(CaptchaError("unsolved")) == STAGE_AUTH
