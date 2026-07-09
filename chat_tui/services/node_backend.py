"""Lifecycle helper for the local Node backend."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from chat_tui.services.server_client import ServerClient


class BackendStartupError(Exception):
    """Raised when the local Node backend cannot be started."""


class NodeBackendSupervisor:
    def __init__(self, server_url: str, repo_root: Path | None = None) -> None:
        self.server_url = server_url
        self.repo_root = repo_root or Path(__file__).resolve().parents[2]
        self.process: asyncio.subprocess.Process | None = None

    @property
    def started_by_tui(self) -> bool:
        return self.process is not None

    async def ensure_running(self, server: ServerClient, timeout: float = 8.0) -> str:
        if await server.health():
            return "existing"

        package_json = self.repo_root / "package.json"
        server_entry = self.repo_root / "server" / "index.js"
        if not package_json.exists() or not server_entry.exists():
            raise BackendStartupError(f"Node backend files not found in {self.repo_root}")

        env = os.environ.copy()
        port = _port_from_url(self.server_url)
        if port:
            env["YOUTUBE_PROXY_PORT"] = str(port)

        try:
            self.process = await asyncio.create_subprocess_exec(
                "npm",
                "run",
                "server",
                cwd=self.repo_root,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise BackendStartupError("npm was not found; install Node/npm to start the backend") from exc

        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self.process.returncode is not None:
                raise BackendStartupError(f"Node backend exited early with code {self.process.returncode}")
            if await server.health():
                return "started"
            await asyncio.sleep(0.25)

        await self.stop()
        raise BackendStartupError(f"Node backend did not become healthy at {self.server_url}")

    async def stop(self) -> None:
        if not self.process:
            return
        proc = self.process
        self.process = None
        if proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


def _port_from_url(url: str) -> int | None:
    parsed = urlparse(url)
    if parsed.port:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    if parsed.scheme == "http":
        return 80
    return None
