"""Metal (Apple GPU) backend for the ALTCHA proof-of-work, optional via ``[metal]``.

Installs as ``pip install 'sigaa-tools[metal]'`` (``pyobjc-framework-Metal``).
The shader is compiled at runtime from the embedded MSL source — Apple's Metal
runtime ships the compiler, so no Xcode toolchain is needed. On any failure
(no Metal device, compile error, wrong output) this module raises
``MetalUnavailable`` and :func:`sigaa.altcha.solve_challenge` falls back to the
CPU solver, so the extra only ever changes speed, never behaviour. Force a
backend with ``SIGAA_ALTCHA_BACKEND=cpu|metal|auto`` (default ``auto``).

The kernel is the one benchmarked and verified byte-for-byte against Apple's
CommonCrypto in the ALTCHA study: a fully unrolled SHA-256 compression (16-word
rolling schedule, indices literal so state lives in registers) driving PBKDF2
in the exact HMAC shape the widget uses — key = nonce ‖ big-endian uint32
counter, 32-byte key, U1 from ``salt ‖ INT(1)``. One GPU thread per counter;
the lowest matching counter wins via an atomic min. Batches start at 4096 and
double on a miss, so SIGAA's current difficulty (~256 attempts) usually clears
in one dispatch (~65 ms floor on an M5) and the recommended counter (10 000)
in two. The winning key is re-derived with hashlib before it is returned, so a
key the CPU would not produce is never posted.

This solver answers this tool's own login — one solve per login, like a
browser ticking the widget. It is not a bulk solver, and never targets
third parties; server-side rate limiting remains SIGAA's real defence.
"""

from __future__ import annotations

import hashlib
import struct
import threading
import time

from .altcha import MAX_COUNTER, CaptchaError, Challenge, Solution

# Prefix lengths the kernel compares in ≤4 words. Everything else (odd hex
# length, longer prefixes, other key lengths) stays on the CPU solver, which
# is fully general; SIGAA uses "00" and deterministic mode 16 bytes.
_MAX_PREFIX_BYTES = 16
_REQUIRED_NONCE_SALT = 16

# One dispatch has a fixed ~65ms floor on an M5 (measured), so batches start
# large: 4096 clears SIGAA's random effort (~256 attempts on average) in a
# single dispatch, and doubling covers the recommended counter 10000 in two.
_BATCH_START = 4096
_MAX_BATCH = 16384
# A dispatch lasts as long as one counter's whole derivation, whatever the
# batch size: about 13 us per iteration on an M5 (the ~65ms floor above is
# SIGAA's cost of 5000). The timeout is only checked between dispatches and a
# dispatch cannot be interrupted, so a cost that would hold the GPU for more
# than ~2s is left to the CPU solver, which checks the clock every attempt.
_MAX_COST = 150_000
_THREADS_PER_GROUP_CAP = 256

# First-use self-check: a tiny known challenge solved on the GPU and compared
# against hashlib. Catches a driver/compiler/kernel discrepancy at startup
# with a clean fallback instead of a rejected login. Counter 752 is the first
# whose key starts with the SIGAA prefix "00" for this fixed nonce/salt.
_SELF_CHECK_NONCE = "3016cc87fed81d41d9f0dc767169159f"
_SELF_CHECK_SALT = "d22ddfafba367c98c9d14b0f6a8d3ced"
_SELF_CHECK_COST = 10
_SELF_CHECK_COUNTER = 752

SHADER_SOURCE = r"""
#include <metal_stdlib>
using namespace metal;

constant uint K[64] = {
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
constant uint IV[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                       0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};

static inline uint rotr(uint x, uint n) { return (x >> n) | (x << (32 - n)); }

// Fully unrolled SHA-256 compression: a rolling 16-word schedule (no w[64]), every index a
// literal so everything lives in registers, and the a..h "rotation" done by renaming
// arguments instead of moving values. Once inlined, constant message words (the HMAC
// padding and length) fold into the schedule at compile time.
#define S0(x)  (rotr(x, 2) ^ rotr(x, 13) ^ rotr(x, 22))
#define S1(x)  (rotr(x, 6) ^ rotr(x, 11) ^ rotr(x, 25))
#define s0(x)  (rotr(x, 7) ^ rotr(x, 18) ^ ((x) >> 3))
#define s1(x)  (rotr(x, 17) ^ rotr(x, 19) ^ ((x) >> 10))
#define CH(e, f, g)  ((g) ^ ((e) & ((f) ^ (g))))
#define MAJ(a, b, c) (((a) & (b)) | ((c) & ((a) | (b))))
#define EXP(i) w[(i) & 15] += s1(w[((i) - 2) & 15]) + w[((i) - 7) & 15] + s0(w[((i) - 15) & 15])
#define RND(a, b, c, d, e, f, g, h, i) { \
    uint t1 = h + S1(e) + CH(e, f, g) + K[i] + w[(i) & 15]; \
    h = t1 + S0(a) + MAJ(a, b, c); d += t1; }
#define RNDE(a, b, c, d, e, f, g, h, i) { EXP(i); RND(a, b, c, d, e, f, g, h, i) }
#define R8(R, i) \
    R(a, b, c, d, e, f, g, h, (i));     R(h, a, b, c, d, e, f, g, (i) + 1); \
    R(g, h, a, b, c, d, e, f, (i) + 2); R(f, g, h, a, b, c, d, e, (i) + 3); \
    R(e, f, g, h, a, b, c, d, (i) + 4); R(d, e, f, g, h, a, b, c, (i) + 5); \
    R(c, d, e, f, g, h, a, b, (i) + 6); R(b, c, d, e, f, g, h, a, (i) + 7);

static inline __attribute__((always_inline)) void compress(thread uint *st, thread const uint *blk) {
  uint w[16];
  #pragma unroll
  for (int i = 0; i < 16; i++) w[i] = blk[i];
  uint a = st[0], b = st[1], c = st[2], d = st[3], e = st[4], f = st[5], g = st[6], h = st[7];
  R8(RND, 0)  R8(RND, 8)
  R8(RNDE, 16) R8(RNDE, 24) R8(RNDE, 32) R8(RNDE, 40) R8(RNDE, 48) R8(RNDE, 56)
  st[0] += a; st[1] += b; st[2] += c; st[3] += d; st[4] += e; st[5] += f; st[6] += g; st[7] += h;
}

// PBKDF2 params, one uint32 each: nonce/salt/target as big-endian words,
// then the batch's first counter, the iteration count, the key-prefix length
// in bytes (1..16) and how many counters this dispatch covers.
struct Params {
  uint nonce[4]; uint salt[4]; uint target[4];
  uint base; uint cost; uint plen; uint count;
};

// Key bytes are serialized big-endian, so prefix byte 0 is the top byte of t[0].
static bool prefix_hit(thread const uint *t, constant uint *tgt, uint n) {
  uint full = n >> 2u;
  for (uint i = 0; i < full; ++i) if (t[i] != tgt[i]) return false;
  uint rem = n & 3u;
  if (rem) {
    uint shift = 8u * (4u - rem);
    if ((t[full] >> shift) != (tgt[full] >> shift)) return false;
  }
  return true;
}

static inline __attribute__((always_inline))
void pbkdf2_body(constant Params &p, device uint *out, device atomic_uint *found, uint gid) {
  if (gid >= p.count) return;
  uint blk[16];

  // HMAC key = nonce(16) || counter(4, big-endian), zero padded to 64 bytes
  uint ist[8], ost[8];
  for (int i = 0; i < 8; i++) { ist[i] = IV[i]; ost[i] = IV[i]; }
  for (int i = 0; i < 16; i++) blk[i] = (i < 4 ? p.nonce[i] : (i == 4 ? p.base + gid : 0u)) ^ 0x36363636u;
  compress(ist, blk);
  for (int i = 0; i < 16; i++) blk[i] ^= 0x36363636u ^ 0x5c5c5c5cu;
  compress(ost, blk);

  // U1 = HMAC(P, salt || INT(1))
  uint st[8], u[8], t[8];
  for (int i = 0; i < 8; i++) st[i] = ist[i];
  for (int i = 0; i < 4; i++) blk[i] = p.salt[i];
  blk[4] = 1; blk[5] = 0x80000000u;
  for (int i = 6; i < 15; i++) blk[i] = 0;
  blk[15] = (64 + 20) * 8;
  compress(st, blk);
  for (int i = 0; i < 8; i++) blk[i] = st[i];
  blk[8] = 0x80000000u;
  for (int i = 9; i < 15; i++) blk[i] = 0;
  blk[15] = (64 + 32) * 8;
  for (int i = 0; i < 8; i++) st[i] = ost[i];
  compress(st, blk);
  for (int i = 0; i < 8; i++) { u[i] = st[i]; t[i] = st[i]; }

  // U2..Uc: 2 compressions per iteration. The padding/length words are re-set as literals
  // inside the loop so the unrolled compressor can constant-fold them.
  for (uint it = 1; it < p.cost; it++) {
    #pragma unroll
    for (int i = 0; i < 8; i++) { blk[i] = u[i]; st[i] = ist[i]; }
    blk[8] = 0x80000000u; blk[9] = 0; blk[10] = 0; blk[11] = 0;
    blk[12] = 0; blk[13] = 0; blk[14] = 0; blk[15] = (64 + 32) * 8;
    compress(st, blk);
    #pragma unroll
    for (int i = 0; i < 8; i++) { blk[i] = st[i]; st[i] = ost[i]; }
    compress(st, blk);
    #pragma unroll
    for (int i = 0; i < 8; i++) { u[i] = st[i]; t[i] ^= st[i]; }
  }

  for (int i = 0; i < 8; i++) out[gid * 8 + i] = t[i];
  if (prefix_hit(t, p.target, p.plen)) {
    atomic_fetch_min_explicit(found, gid, memory_order_relaxed);
  }
}

kernel void pbkdf2(constant Params &p [[buffer(0)]], device uint *out [[buffer(1)]],
                   device atomic_uint *found [[buffer(2)]], uint gid [[thread_position_in_grid]]) {
  pbkdf2_body(p, out, found, gid);
}
"""


class MetalUnavailable(RuntimeError):
    """Metal cannot solve here (no device, compile failure, wrong output).

    Never escapes :func:`sigaa.altcha.solve_challenge` unless the backend is
    forced with ``SIGAA_ALTCHA_BACKEND=metal``; it is the CPU-fallback signal.
    """


# ("ready", solver) after a successful init, ("failed", MetalUnavailable) once
# init has failed: recompiling the shader per login would only repeat the error.
_STATE: tuple[str, "MetalSolver | MetalUnavailable | None"] = ("new", None)


def available() -> bool:
    """Whether this machine has a Metal device the extra can drive."""
    try:
        import Metal

        return Metal.MTLCreateSystemDefaultDevice() is not None
    except Exception:
        return False


def solve(
    challenge: Challenge,
    *,
    max_attempts: int = 100_000,
    timeout_seconds: float = 90.0,
) -> Solution:
    """Solve on the GPU, or raise ``MetalUnavailable`` to fall back to CPU."""
    global _STATE
    kind, state = _STATE
    if kind == "failed":
        raise state
    if kind != "ready":
        try:
            state = MetalSolver()
            _STATE = ("ready", state)
        except MetalUnavailable as exc:
            _STATE = ("failed", exc)
            raise
        except Exception as exc:  # driver/pyobjc surprises become the same signal
            failure = MetalUnavailable(f"Metal init failed: {exc}")
            _STATE = ("failed", failure)
            raise failure from None
    return state.solve(
        challenge, max_attempts=max_attempts, timeout_seconds=timeout_seconds
    )


class MetalSolver:
    def __init__(self):
        import Metal

        device = Metal.MTLCreateSystemDefaultDevice()
        if device is None:
            raise MetalUnavailable("no Metal device on this machine")
        self._Metal = Metal
        self._device = device
        library, error = device.newLibraryWithSource_options_error_(
            SHADER_SOURCE, None, None
        )
        if library is None:
            raise MetalUnavailable(f"shader compile failed: {error}")
        function = library.newFunctionWithName_("pbkdf2")
        pipeline, error = device.newComputePipelineStateWithFunction_error_(
            function, None
        )
        if pipeline is None:
            raise MetalUnavailable(f"pipeline build failed: {error}")
        self._pipeline = pipeline
        self._queue = device.newCommandQueue()
        # Every thread writes its 32-byte key, so the batch buffer covers the
        # largest dispatch.
        self._keys = device.newBufferWithLength_options_(_MAX_BATCH * 32, 0)
        # The solver is a process-wide singleton and its key buffer is shared:
        # a dispatch and the read of its winning key must not interleave with
        # another caller's dispatch.
        self._dispatch_lock = threading.Lock()
        self._self_check()

    def solve(
        self,
        challenge: Challenge,
        *,
        max_attempts: int = 100_000,
        timeout_seconds: float = 90.0,
    ) -> Solution:
        # Limits of the verified kernel; anything else stays on the CPU solver.
        if challenge.algorithm != "PBKDF2/SHA-256" or challenge.key_length != 32:
            raise MetalUnavailable("GPU kernel only does PBKDF2/SHA-256 with 32-byte keys")
        nonce = bytes.fromhex(challenge.nonce)
        salt = bytes.fromhex(challenge.salt)
        if len(nonce) != _REQUIRED_NONCE_SALT or len(salt) != _REQUIRED_NONCE_SALT:
            raise MetalUnavailable("GPU kernel expects a 16-byte nonce and salt")
        if challenge.cost > _MAX_COST:
            raise MetalUnavailable(f"GPU dispatch would outlast the timeout check above cost {_MAX_COST}")
        prefix = _whole_byte_prefix(challenge.key_prefix)
        target = [0, 0, 0, 0]
        for index, byte in enumerate(prefix):
            target[index // 4] |= byte << (8 * (3 - index % 4))

        started = time.monotonic()
        # Same bound as the CPU solver: max_attempts derivations, counters from 0.
        limit = min(max_attempts, MAX_COUNTER + 1)
        base, batch = 0, _BATCH_START
        while base < limit:
            batch = min(batch, limit - base)
            hit = self._run_batch(nonce, salt, target, len(prefix), challenge.cost, base, batch)
            if hit is not None:
                offset, key = hit
                counter = base + offset
                self._verify(challenge, nonce, salt, counter, key)
                return Solution(
                    counter=counter,
                    derived_key=key,
                    time_ms=(time.monotonic() - started) * 1000,
                )
            base += batch
            batch = min(batch * 2, _MAX_BATCH)
            if time.monotonic() - started > timeout_seconds:
                raise CaptchaError(
                    f"ALTCHA not solved within {timeout_seconds:g}s "
                    f"({base} attempts, prefix {challenge.key_prefix!r})"
                )
        raise CaptchaError(
            f"ALTCHA not solved after {max_attempts} attempts "
            f"(prefix {challenge.key_prefix!r})"
        )

    @staticmethod
    def _verify(challenge: Challenge, nonce: bytes, salt: bytes, counter: int, key: str) -> None:
        """Refuse a GPU answer the CPU would not give: one derivation, <1 ms.

        This is what makes the GPU a speed-only change. A kernel or driver
        fault, or a key read from another dispatch, ends in the CPU fallback
        instead of a rejected login.
        """
        expected = hashlib.pbkdf2_hmac(
            "sha256", nonce + struct.pack(">I", counter), salt, challenge.cost, 32
        ).hex()
        if key != expected or not expected.startswith(challenge.key_prefix.lower()):
            raise MetalUnavailable("GPU answer disagrees with hashlib at the winning counter")

    def _run_batch(
        self,
        nonce: bytes,
        salt: bytes,
        target: list[int],
        prefix_bytes: int,
        cost: int,
        base: int,
        count: int,
    ) -> tuple[int, str] | None:
        """Dispatch one batch; return the winning counter's offset and key, or None."""
        Metal = self._Metal
        params = struct.pack(
            "<16I",
            *struct.unpack(">4I", nonce),
            *struct.unpack(">4I", salt),
            *target,
            base,
            cost,
            prefix_bytes,
            count,
        )
        with self._dispatch_lock:
            params_buffer = self._device.newBufferWithBytes_length_options_(
                params, len(params), 0
            )
            found_buffer = self._device.newBufferWithBytes_length_options_(
                struct.pack("<I", 0xFFFFFFFF), 4, 0
            )
            command = self._queue.commandBuffer()
            encoder = command.computeCommandEncoder()
            encoder.setComputePipelineState_(self._pipeline)
            encoder.setBuffer_offset_atIndex_(params_buffer, 0, 0)
            encoder.setBuffer_offset_atIndex_(self._keys, 0, 1)
            encoder.setBuffer_offset_atIndex_(found_buffer, 0, 2)
            threads = min(
                _THREADS_PER_GROUP_CAP, self._pipeline.maxTotalThreadsPerThreadgroup()
            )
            encoder.dispatchThreads_threadsPerThreadgroup_(
                Metal.MTLSizeMake(count, 1, 1), Metal.MTLSizeMake(threads, 1, 1)
            )
            encoder.endEncoding()
            command.commit()
            command.waitUntilCompleted()
            if command.error() is not None:
                raise MetalUnavailable(f"GPU dispatch failed: {command.error()}")
            found = struct.unpack("<I", b"".join(found_buffer.contents()[:4]))[0]
            if found == 0xFFFFFFFF:
                return None
            return found, self._key(found)

    def _key(self, gid: int) -> str:
        raw = b"".join(self._keys.contents()[gid * 32 : (gid + 1) * 32])
        # The kernel stores the SHA-256 state words natively; the key is their
        # big-endian serialization.
        return struct.pack(">8I", *struct.unpack("<8I", raw)).hex()

    def _self_check(self) -> None:
        hit = self._run_batch(
            bytes.fromhex(_SELF_CHECK_NONCE),
            bytes.fromhex(_SELF_CHECK_SALT),
            [0, 0, 0, 0],
            1,
            _SELF_CHECK_COST,
            _SELF_CHECK_COUNTER,
            1,
        )
        if hit is None or hit[0] != 0:
            raise MetalUnavailable("GPU self-check did not produce its known key")
        expected = hashlib.pbkdf2_hmac(
            "sha256",
            bytes.fromhex(_SELF_CHECK_NONCE) + struct.pack(">I", _SELF_CHECK_COUNTER),
            bytes.fromhex(_SELF_CHECK_SALT),
            _SELF_CHECK_COST,
            32,
        ).hex()
        if hit[1] != expected:
            raise MetalUnavailable("GPU output disagrees with hashlib at the self-check")


def _whole_byte_prefix(key_prefix: str) -> bytes:
    """The prefix as bytes, or ``MetalUnavailable`` when the kernel cannot compare it.

    The widget compares hex text, so an odd-length prefix ("0", "000") is valid;
    the kernel compares whole bytes. Those, and anything not hexadecimal, belong
    to the CPU solver.
    """
    if len(key_prefix) % 2:
        raise MetalUnavailable("GPU kernel compares whole-byte prefixes only")
    try:
        prefix = bytes.fromhex(key_prefix)
    except ValueError:
        raise MetalUnavailable("GPU kernel needs a hexadecimal prefix") from None
    if not 1 <= len(prefix) <= _MAX_PREFIX_BYTES:
        raise MetalUnavailable(f"GPU kernel compares prefixes of 1..{_MAX_PREFIX_BYTES} bytes")
    return prefix
