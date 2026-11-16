"""CUDA (NVIDIA GPU) backend for the ALTCHA proof-of-work, optional via ``[cuda]``.

Installs as ``pip install 'sigaa-tools[cuda]'`` (``cuda-bindings`` plus the
``nvidia-cuda-nvrtc`` wheel). The kernel is compiled at runtime by NVRTC from
the embedded CUDA C source, so no CUDA Toolkit or ``nvcc`` is needed — only the
NVIDIA display driver every GPU machine already has. On any failure (no driver,
no device, compile error, wrong output) this module raises ``CudaUnavailable``
and :func:`sigaa.altcha.solve_challenge` falls back to the next backend and
finally to the CPU solver, so the extra only ever changes speed, never
behaviour. Force a backend with ``SIGAA_ALTCHA_BACKEND=cpu|metal|cuda|auto``.

It is the same algorithm as :mod:`sigaa.altcha_metal`, ported to CUDA C: a fully
unrolled SHA-256 compression driving PBKDF2 in the exact HMAC shape the widget
uses — key = nonce ‖ big-endian uint32 counter, 32-byte key, U1 from
``salt ‖ INT(1)``. One GPU thread per counter; the lowest matching counter wins
via an atomic min. The winning key is re-derived with hashlib before it is
returned, so a key the CPU would not produce is never posted.

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

# Prefix lengths the kernel compares in <=4 words. Everything else (odd hex
# length, longer prefixes, other key lengths) stays on the CPU solver, which is
# fully general; SIGAA uses "00" and deterministic mode 16 bytes.
_MAX_PREFIX_BYTES = 16
_REQUIRED_NONCE_SALT = 16

# Batches start large so SIGAA's random effort (~256 attempts on average)
# clears in one dispatch, and double on a miss to cover the recommended counter
# 10000 in two.
_BATCH_START = 4096
_MAX_BATCH = 16384
# A dispatch lasts as long as one counter's whole derivation whatever the batch
# size, and cannot be interrupted. Display GPUs on Windows are reset by the
# driver (TDR) after ~2s in one kernel, so a cost that could approach that is
# left to the CPU solver, which checks the clock every attempt. The bound is
# conservative and not yet calibrated against a measured per-iteration time.
_MAX_COST = 100_000
_THREADS_PER_BLOCK_CAP = 256

# First-use self-check: a tiny known challenge solved on the GPU and compared
# against hashlib. Counter 752 is the first whose key starts with the SIGAA
# prefix "00" for this fixed nonce/salt.
_SELF_CHECK_NONCE = "3016cc87fed81d41d9f0dc767169159f"
_SELF_CHECK_SALT = "d22ddfafba367c98c9d14b0f6a8d3ced"
_SELF_CHECK_COST = 10
_SELF_CHECK_COUNTER = 752

SHADER_SOURCE = r"""
typedef unsigned int uint;

__constant__ uint K[64] = {
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
__constant__ uint IV[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                           0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};

__device__ __forceinline__ uint rotr(uint x, uint n) { return __funnelshift_r(x, x, n); }

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

__device__ __forceinline__ void compress(uint *st, const uint *blk) {
  uint w[16];
  #pragma unroll
  for (int i = 0; i < 16; i++) w[i] = blk[i];
  uint a = st[0], b = st[1], c = st[2], d = st[3], e = st[4], f = st[5], g = st[6], h = st[7];
  R8(RND, 0)  R8(RND, 8)
  R8(RNDE, 16) R8(RNDE, 24) R8(RNDE, 32) R8(RNDE, 40) R8(RNDE, 48) R8(RNDE, 56)
  st[0] += a; st[1] += b; st[2] += c; st[3] += d; st[4] += e; st[5] += f; st[6] += g; st[7] += h;
}

// Parameters, one uint32 each, in one device buffer p[16]: nonce[0..3], salt[4..7] and
// target[8..11] as big-endian words, then the batch's first counter (12), the iteration
// count (13), the key-prefix length in bytes 1..16 (14) and how many counters this
// dispatch covers (15).

// Key bytes are serialized big-endian, so prefix byte 0 is the top byte of t[0].
__device__ __forceinline__ bool prefix_hit(const uint *t, const uint *tgt, uint n) {
  uint full = n >> 2u;
  for (uint i = 0; i < full; ++i) if (t[i] != tgt[i]) return false;
  uint rem = n & 3u;
  if (rem) {
    uint shift = 8u * (4u - rem);
    if ((t[full] >> shift) != (tgt[full] >> shift)) return false;
  }
  return true;
}

extern "C" __global__ void pbkdf2(const uint *p, uint *out, uint *found) {
  uint gid = blockIdx.x * blockDim.x + threadIdx.x;
  if (gid >= p[15]) return;
  uint cost = p[13];
  uint blk[16];

  // HMAC key = nonce(16) || counter(4, big-endian), zero padded to 64 bytes
  uint ist[8], ost[8];
  for (int i = 0; i < 8; i++) { ist[i] = IV[i]; ost[i] = IV[i]; }
  for (int i = 0; i < 16; i++) blk[i] = (i < 4 ? p[i] : (i == 4 ? p[12] + gid : 0u)) ^ 0x36363636u;
  compress(ist, blk);
  for (int i = 0; i < 16; i++) blk[i] ^= 0x36363636u ^ 0x5c5c5c5cu;
  compress(ost, blk);

  // U1 = HMAC(P, salt || INT(1))
  uint st[8], u[8], t[8];
  for (int i = 0; i < 8; i++) st[i] = ist[i];
  for (int i = 0; i < 4; i++) blk[i] = p[4 + i];
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
  for (uint it = 1; it < cost; it++) {
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

  if (prefix_hit(t, p + 8, p[14])) {
    for (int i = 0; i < 8; i++) out[gid * 8 + i] = t[i];
    atomicMin(found, gid);
  }
}
"""


class CudaUnavailable(RuntimeError):
    """CUDA cannot solve here (no driver, no device, compile failure, wrong output).

    Never escapes :func:`sigaa.altcha.solve_challenge` unless the backend is
    forced with ``SIGAA_ALTCHA_BACKEND=cuda``; it is the fallback signal.
    """


# ("ready", solver) after a successful init, ("failed", CudaUnavailable) once
# init has failed: recompiling the kernel per login would only repeat the error.
_STATE: tuple[str, "CudaSolver | CudaUnavailable | None"] = ("new", None)


def _load_bindings():
    """``(driver, nvrtc)`` from cuda-bindings, under either of its module layouts."""
    try:
        from cuda.bindings import driver, nvrtc
    except ImportError:
        from cuda import cuda as driver, nvrtc  # cuda-python < 12.9
    return driver, nvrtc


def _check(result, what: str):
    """Unpack a cuda-bindings ``(error, *values)`` tuple, raising on a non-zero error."""
    error, *values = result
    if int(error) != 0:
        raise CudaUnavailable(f"{what} failed: {error}")
    return values[0] if len(values) == 1 else (tuple(values) or None)


def available() -> bool:
    """Whether this machine has an NVIDIA device the extra can drive."""
    try:
        driver, _ = _load_bindings()
        _check(driver.cuInit(0), "cuInit")
        return _check(driver.cuDeviceGetCount(), "cuDeviceGetCount") > 0
    except Exception:
        return False


def solve(
    challenge: Challenge,
    *,
    max_attempts: int = 100_000,
    timeout_seconds: float = 90.0,
) -> Solution:
    """Solve on the GPU, or raise ``CudaUnavailable`` to fall back."""
    global _STATE
    kind, state = _STATE
    if kind == "failed":
        raise state
    if kind != "ready":
        try:
            state = CudaSolver()
            _STATE = ("ready", state)
        except CudaUnavailable as exc:
            _STATE = ("failed", exc)
            raise
        except Exception as exc:  # missing driver library, binding surprises...
            failure = CudaUnavailable(f"CUDA init failed: {exc}")
            _STATE = ("failed", failure)
            raise failure from None
    return state.solve(
        challenge, max_attempts=max_attempts, timeout_seconds=timeout_seconds
    )


class CudaSolver:
    def __init__(self):
        driver, nvrtc = _load_bindings()
        self._driver = driver
        _check(driver.cuInit(0), "cuInit")
        if _check(driver.cuDeviceGetCount(), "cuDeviceGetCount") < 1:
            raise CudaUnavailable("no CUDA device on this machine")
        device = _check(driver.cuDeviceGet(0), "cuDeviceGet")
        attribute = driver.CUdevice_attribute
        major = _check(
            driver.cuDeviceGetAttribute(
                attribute.CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MAJOR, device
            ),
            "cuDeviceGetAttribute",
        )
        minor = _check(
            driver.cuDeviceGetAttribute(
                attribute.CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MINOR, device
            ),
            "cuDeviceGetAttribute",
        )
        # The primary context is the one other CUDA code in the process shares;
        # it is made current on whichever thread dispatches (see _run_batch).
        self._context = _check(
            driver.cuDevicePrimaryCtxRetain(device), "cuDevicePrimaryCtxRetain"
        )
        _check(driver.cuCtxSetCurrent(self._context), "cuCtxSetCurrent")

        cubin = _compile(nvrtc, f"sm_{major}{minor}")
        module = _check(driver.cuModuleLoadData(cubin), "cuModuleLoadData")
        self._function = _check(
            driver.cuModuleGetFunction(module, b"pbkdf2"), "cuModuleGetFunction"
        )
        max_threads = _check(
            driver.cuFuncGetAttribute(
                driver.CUfunction_attribute.CU_FUNC_ATTRIBUTE_MAX_THREADS_PER_BLOCK,
                self._function,
            ),
            "cuFuncGetAttribute",
        )
        self._threads = max(1, min(_THREADS_PER_BLOCK_CAP, max_threads))
        self._params = _check(driver.cuMemAlloc(16 * 4), "cuMemAlloc")
        self._found = _check(driver.cuMemAlloc(4), "cuMemAlloc")
        # Only threads that hit write their key, so the buffer covers the
        # largest dispatch but is read one 32-byte key at a time.
        self._keys = _check(driver.cuMemAlloc(_MAX_BATCH * 32), "cuMemAlloc")
        # The solver is a process-wide singleton and its buffers are shared: a
        # dispatch and the read of its winning key must not interleave with
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
            raise CudaUnavailable("GPU kernel only does PBKDF2/SHA-256 with 32-byte keys")
        nonce = bytes.fromhex(challenge.nonce)
        salt = bytes.fromhex(challenge.salt)
        if len(nonce) != _REQUIRED_NONCE_SALT or len(salt) != _REQUIRED_NONCE_SALT:
            raise CudaUnavailable("GPU kernel expects a 16-byte nonce and salt")
        if challenge.cost > _MAX_COST:
            raise CudaUnavailable(
                f"GPU dispatch would outlast the timeout check above cost {_MAX_COST}"
            )
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
            raise CudaUnavailable("GPU answer disagrees with hashlib at the winning counter")

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
        driver = self._driver
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
        blocks = (count + self._threads - 1) // self._threads
        with self._dispatch_lock:
            # A CUDA context is current per thread; solves can come from any.
            _check(driver.cuCtxSetCurrent(self._context), "cuCtxSetCurrent")
            _check(driver.cuMemcpyHtoD(self._params, params, len(params)), "cuMemcpyHtoD")
            _check(driver.cuMemsetD32(self._found, 0xFFFFFFFF, 1), "cuMemsetD32")
            _check(
                driver.cuLaunchKernel(
                    self._function,
                    blocks, 1, 1,
                    self._threads, 1, 1,
                    0, 0,
                    ((self._params, self._keys, self._found), (None, None, None)),
                    0,
                ),
                "cuLaunchKernel",
            )
            _check(driver.cuCtxSynchronize(), "GPU dispatch")
            found_raw = bytearray(4)
            _check(driver.cuMemcpyDtoH(found_raw, self._found, 4), "cuMemcpyDtoH")
            found = struct.unpack("<I", found_raw)[0]
            if found == 0xFFFFFFFF:
                return None
            return found, self._key(found)

    def _key(self, gid: int) -> str:
        driver = self._driver
        raw = bytearray(32)
        source = driver.CUdeviceptr(int(self._keys) + gid * 32)
        _check(driver.cuMemcpyDtoH(raw, source, 32), "cuMemcpyDtoH")
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
            raise CudaUnavailable("GPU self-check did not produce its known key")
        expected = hashlib.pbkdf2_hmac(
            "sha256",
            bytes.fromhex(_SELF_CHECK_NONCE) + struct.pack(">I", _SELF_CHECK_COUNTER),
            bytes.fromhex(_SELF_CHECK_SALT),
            _SELF_CHECK_COST,
            32,
        ).hex()
        if hit[1] != expected:
            raise CudaUnavailable("GPU output disagrees with hashlib at the self-check")


def _compile(nvrtc, architecture: str) -> bytearray:
    """NVRTC-compile the kernel to a CUBIN for ``architecture`` (e.g. ``sm_86``)."""
    program = _check(
        nvrtc.nvrtcCreateProgram(SHADER_SOURCE.encode(), b"pbkdf2.cu", 0, [], []),
        "nvrtcCreateProgram",
    )
    try:
        options = [f"--gpu-architecture={architecture}".encode()]
        error = nvrtc.nvrtcCompileProgram(program, len(options), options)[0]
        if int(error) != 0:
            log_size = _check(nvrtc.nvrtcGetProgramLogSize(program), "nvrtcGetProgramLogSize")
            log = bytearray(log_size)
            nvrtc.nvrtcGetProgramLog(program, log)
            text = bytes(log).rstrip(b"\0").decode(errors="replace")
            raise CudaUnavailable(f"kernel compile failed for {architecture}: {text}")
        size = _check(nvrtc.nvrtcGetCUBINSize(program), "nvrtcGetCUBINSize")
        cubin = bytearray(size)
        _check(nvrtc.nvrtcGetCUBIN(program, cubin), "nvrtcGetCUBIN")
        return cubin
    finally:
        nvrtc.nvrtcDestroyProgram(program)


def _whole_byte_prefix(key_prefix: str) -> bytes:
    """The prefix as bytes, or ``CudaUnavailable`` when the kernel cannot compare it.

    The widget compares hex text, so an odd-length prefix ("0", "000") is valid;
    the kernel compares whole bytes. Those, and anything not hexadecimal, belong
    to the CPU solver.
    """
    if len(key_prefix) % 2:
        raise CudaUnavailable("GPU kernel compares whole-byte prefixes only")
    try:
        prefix = bytes.fromhex(key_prefix)
    except ValueError:
        raise CudaUnavailable("GPU kernel needs a hexadecimal prefix") from None
    if not 1 <= len(prefix) <= _MAX_PREFIX_BYTES:
        raise CudaUnavailable(f"GPU kernel compares prefixes of 1..{_MAX_PREFIX_BYTES} bytes")
    return prefix
