"""CUDA GPU backend.

Three layers, so most of it runs without an NVIDIA GPU:

- the kernel source is compiled for the host with a tiny CUDA shim and checked
  against hashlib (needs only a C++ compiler; skipped without one);
- error handling and the prefix/cost limits, with the CUDA bindings absent;
- the live tests, skipped unless a CUDA device and driver are present.
"""

import hashlib
import json
import secrets
import shutil
import struct
import subprocess
import sys
import threading

import pytest

from sigaa import altcha, altcha_cuda
from sigaa.altcha import BACKEND_ENV, Challenge, parse_challenge, solve_challenge
from sigaa.errors import CaptchaError

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


def _challenge(prefix, *, cost=10, nonce=NONCE, salt=SALT):
    return Challenge("PBKDF2/SHA-256", cost, 32, prefix, nonce, salt, "s" * 64, {})


@pytest.fixture
def no_bindings(monkeypatch):
    """cuda-bindings not installed, whatever this machine has."""
    monkeypatch.setitem(sys.modules, "cuda", None)
    monkeypatch.setitem(sys.modules, "cuda.bindings", None)
    monkeypatch.setattr(altcha_cuda, "_STATE", ("new", None))


# --- the kernel source, run on the host --------------------------------------

_SHIM = r"""
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#define __global__
#define __device__
#define __constant__ static const
#define __forceinline__ inline
struct U3 { unsigned x; };
static U3 threadIdx, blockIdx, blockDim;
static inline unsigned __funnelshift_r(unsigned lo, unsigned hi, unsigned n) {
  return (unsigned)((((uint64_t)hi << 32) | lo) >> (n & 31)); }
static inline unsigned atomicMin(unsigned *a, unsigned v) {
  unsigned o = *a; if (v < o) *a = v; return o; }
"""

_MAIN = r"""
int main(int argc, char **argv) {
  unsigned p[16];
  for (int i = 0; i < 16; i++) p[i] = (unsigned)strtoul(argv[1 + i], 0, 10);
  static unsigned out[16384 * 8];
  unsigned found = 0xFFFFFFFFu;
  blockDim.x = 1;
  for (unsigned g = 0; g < p[15]; g++) { blockIdx.x = g; threadIdx.x = 0; pbkdf2(p, out, &found); }
  printf("%u", found);
  if (found != 0xFFFFFFFFu) for (int i = 0; i < 8; i++) printf(" %08x", out[found * 8 + i]);
  printf("\n");
  return 0;
}
"""


@pytest.fixture(scope="module")
def host_kernel(tmp_path_factory):
    """The CUDA kernel compiled as plain C++: one 'thread' per counter, in a loop."""
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("no C++ compiler to run the kernel on the host")
    directory = tmp_path_factory.mktemp("cuda-kernel")
    source = directory / "kernel.cpp"
    source.write_text(_SHIM + altcha_cuda.SHADER_SOURCE + _MAIN)
    binary = directory / "kernel.exe"
    build = subprocess.run(
        [compiler, "-O2", "-o", str(binary), str(source)], capture_output=True, text=True
    )
    assert build.returncode == 0, build.stderr

    def run(prefix, cost, base, count, nonce=NONCE, salt=SALT):
        raw = bytes.fromhex(prefix)
        target = [0, 0, 0, 0]
        for index, byte in enumerate(raw):
            target[index // 4] |= byte << (8 * (3 - index % 4))
        params = [
            *struct.unpack(">4I", bytes.fromhex(nonce)),
            *struct.unpack(">4I", bytes.fromhex(salt)),
            *target, base, cost, len(raw), count,
        ]
        out = subprocess.run(
            [str(binary), *map(str, params)], capture_output=True, text=True, check=True
        ).stdout.split()
        found = int(out[0])
        return (found, "".join(out[1:])) if found != 0xFFFFFFFF else (None, None)

    return run


def test_kernel_reproduces_the_widget_solution(host_kernel):
    challenge = parse_challenge(PLAYGROUND)

    counter, key = host_kernel(
        "00", challenge.cost, 0, 1000, nonce=challenge.nonce, salt=challenge.salt
    )

    assert counter == 377
    assert key == derive(challenge, 377)


def test_kernel_finds_the_self_check_counter(host_kernel):
    counter, key = host_kernel("00", 10, 0, 2000)

    assert counter == altcha_cuda._SELF_CHECK_COUNTER
    assert key == derive(_challenge("00"), counter)


@pytest.mark.parametrize("length", [1, 3, 4, 5, 15, 16])
def test_kernel_compares_prefixes_of_every_word_alignment(host_kernel, length):
    prefix = derive(_challenge("00"), 12)[: length * 2]

    counter, key = host_kernel(prefix, 10, 0, 100)

    # The first counter at or below 12 whose key starts with the prefix; a
    # shorter prefix may match an earlier counter, never a later one.
    assert counter is not None and counter <= 12
    assert key == derive(_challenge("00"), counter)
    assert key.startswith(prefix)


def test_kernel_respects_the_batch_base(host_kernel):
    counter, _ = host_kernel("00", 10, 700, 100)  # 752 is in 700..799

    assert counter == 52


def test_kernel_reports_a_miss(host_kernel):
    assert host_kernel("00" * 16, 10, 0, 50) == (None, None)


# --- without the bindings or a device ----------------------------------------


def test_missing_bindings_are_cuda_unavailable(no_bindings):
    with pytest.raises(altcha_cuda.CudaUnavailable, match="CUDA init failed"):
        altcha_cuda.solve(_challenge("00"))
    # The failure is remembered instead of retried on every login.
    assert altcha_cuda._STATE[0] == "failed"


def test_available_is_false_without_the_bindings(no_bindings):
    assert altcha_cuda.available() is False


def test_forced_cuda_without_bindings_is_a_captcha_failure(monkeypatch, no_bindings):
    monkeypatch.setenv(BACKEND_ENV, "cuda")

    with pytest.raises(CaptchaError, match="CUDA backend requested"):
        solve_challenge(_challenge("00"))


def test_auto_without_bindings_is_solved_on_the_cpu(monkeypatch, no_bindings):
    monkeypatch.setitem(sys.modules, "sigaa.altcha_metal", None)
    challenge = _challenge("00")

    assert solve_challenge(challenge).counter == altcha.solve(challenge).counter


@pytest.mark.parametrize("prefix", ["0", "000", "zz", "00" * 17])
def test_prefix_the_kernel_cannot_compare_is_refused(prefix):
    with pytest.raises(altcha_cuda.CudaUnavailable):
        altcha_cuda._whole_byte_prefix(prefix)


def test_whole_byte_prefix_decodes_hex():
    assert altcha_cuda._whole_byte_prefix("00ff") == b"\x00\xff"


# --- live: a CUDA device and driver --------------------------------------------

live = pytest.mark.skipif(
    not altcha_cuda.available(), reason="no CUDA device on this machine"
)


@live
def test_cuda_reproduces_the_widget_solution():
    solution = altcha_cuda.solve(parse_challenge(PLAYGROUND))

    assert solution.counter == 377
    assert solution.derived_key.startswith("00")


@live
def test_cuda_keys_match_hashlib():
    challenge = parse_challenge(PLAYGROUND)
    solution = altcha_cuda.solve(challenge)

    assert solution.derived_key == derive(challenge, solution.counter)


@live
def test_cuda_solves_the_deterministic_mode():
    key = derive(_challenge("00"), 12)

    assert altcha_cuda.solve(_challenge(key[:32])).counter == 12


@live
def test_solve_challenge_goes_through_the_gpu(monkeypatch):
    monkeypatch.setitem(sys.modules, "sigaa.altcha_metal", None)
    monkeypatch.setitem(sys.modules, "sigaa.altcha_cuda", altcha_cuda)
    challenge = parse_challenge(PLAYGROUND)

    solution = solve_challenge(challenge)

    assert solution.counter == 377
    assert solution.derived_key == derive(challenge, 377)


@live
@pytest.mark.parametrize("prefix", ["0", "000"])
def test_odd_length_prefix_is_solved_like_the_cpu_solves_it(monkeypatch, prefix):
    monkeypatch.setitem(sys.modules, "sigaa.altcha_cuda", altcha_cuda)
    challenge = _challenge(prefix)

    solution = solve_challenge(challenge)

    cpu = altcha.solve(challenge)
    assert (solution.counter, solution.derived_key) == (cpu.counter, cpu.derived_key)


def _solver():
    altcha_cuda.solve(_challenge("00"))  # builds and self-checks the singleton
    return altcha_cuda._STATE[1]


@live
def test_key_from_another_dispatch_is_refused(monkeypatch):
    # A foreign key that also starts with the prefix must not pass the only check.
    challenge = _challenge("00")
    foreign = derive(_challenge("00", nonce=secrets.token_hex(16)), 0)
    foreign = "00" + foreign[2:]
    monkeypatch.setattr(_solver(), "_run_batch", lambda *args: (0, foreign))

    with pytest.raises(altcha_cuda.CudaUnavailable, match="disagrees with hashlib"):
        altcha_cuda.solve(challenge)


@live
def test_concurrent_solves_each_get_their_own_key():
    wrong = []

    def worker():
        for _ in range(20):
            challenge = _challenge(
                "00", cost=50, nonce=secrets.token_hex(16), salt=secrets.token_hex(16)
            )
            solution = altcha_cuda.solve(challenge)
            if solution.derived_key != derive(challenge, solution.counter):
                wrong.append(solution.counter)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert wrong == []


@live
def test_give_up_bounds_match_the_cpu_solver():
    unreachable = _challenge("00" * 16)

    with pytest.raises(CaptchaError, match="after 10 attempts"):
        altcha_cuda.solve(unreachable, max_attempts=10)
    with pytest.raises(CaptchaError, match="after 10 attempts"):
        altcha.solve(unreachable, max_attempts=10)


@live
def test_cost_that_would_hold_the_gpu_too_long_is_left_to_the_cpu():
    with pytest.raises(altcha_cuda.CudaUnavailable, match="cost"):
        altcha_cuda.solve(_challenge("00", cost=altcha_cuda._MAX_COST + 1))
