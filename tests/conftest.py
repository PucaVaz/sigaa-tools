from __future__ import annotations

import os
from pathlib import Path


def mcp_subprocess_env(download_dir: Path, **extra: str) -> dict[str, str]:
    """Env for spawning `python -m sigaa.mcp_server` with no ambient credentials.

    Keyring is nulled and the download dir is redirected into the test's tmp_path so a
    spawned server can never reach the developer's real account or files.
    """
    environment = dict(os.environ)
    environment.pop("SIGAA_USER", None)
    environment.pop("SIGAA_PASS", None)
    environment.pop("SIGAA_MODE", None)
    environment["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    environment["SIGAA_DOWNLOAD_DIR"] = str(download_dir)
    environment.update(extra)
    return environment
