"""The MCP surface itself — nothing else in the suite touches it.

Every other test calls the tool functions directly, so nothing verified that
the server stands up, registers its tools, carries annotations over the wire,
or dispatches a call. That is exactly what a framework upgrade (fastmcp 3 -> 4)
breaks, so this is the safety net for it. No network: the yt-dlp subprocess is
monkeypatched.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

# Settings are read at import time (see test_download_filename.py).
os.environ.setdefault("TRANSPORT", "stdio")
os.environ.setdefault("OUTPUT_DIRECTORY", tempfile.mkdtemp(prefix="mcp_ytdlp_test_"))

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastmcp import Client  # noqa: E402

from mcp_ytdlp import server  # noqa: E402
from mcp_ytdlp.server import mcp  # noqa: E402

pytestmark = pytest.mark.anyio

EXPECTED_TOOLS = {"download_video", "convert_video", "cleanup_files"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_server_registers_its_tools():
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"


async def test_annotations_survive_the_wire():
    # No tool here is read-only, so assert the hints that matter for the
    # destructive one and the network-reaching one, read back through the client.
    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    cleanup = tools["cleanup_files"].annotations
    assert cleanup is not None
    assert cleanup.readOnlyHint is False
    assert cleanup.destructiveHint is True
    download = tools["download_video"].annotations
    assert download is not None
    assert download.openWorldHint is True


async def test_download_round_trips_without_network(tmp_output_dir, monkeypatch):
    expected = Path(tmp_output_dir) / "Generic-abc123.mp4"

    def fake_run(cmd, *args, **kwargs):
        assert cmd[0] == "yt-dlp", f"unexpected subprocess: {cmd}"
        if "--dump-json" in cmd:
            out = '{"id": "abc123", "title": "t", "webpage_url": "https://example.com/v"}'
        else:
            expected.write_bytes(b"\x00\x00\x00\x18ftypmp42")
            out = f"{expected}\n"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)

    async with Client(mcp) as client:
        result = await client.call_tool(
            "download_video", {"url": "https://example.com/v", "output_directory": tmp_output_dir}
        )
    # Union return type, so the wire payload is wrapped under "result".
    payload = result.structured_content["result"]
    assert payload["status"] == "success"
    assert payload["filename"] == "Generic-abc123.mp4"
