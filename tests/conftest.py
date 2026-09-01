from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def mcp_subprocess_env():
    """Factory for the env used to spawn `python -m sigaa.mcp_server` in tests.

    Strips ambient credentials, nulls the keyring backend and redirects the download
    directory into the test's tmp_path, so a spawned server can never reach the
    developer's real account or files. Extra variables are passed as keywords.
    """

    def build(download_dir: Path, **extra: str) -> dict[str, str]:
        environment = dict(os.environ)
        environment.pop("SIGAA_USER", None)
        environment.pop("SIGAA_PASS", None)
        environment.pop("SIGAA_MODE", None)
        environment["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        environment["SIGAA_DOWNLOAD_DIR"] = str(download_dir)
        environment.update(extra)
        return environment

    return build
