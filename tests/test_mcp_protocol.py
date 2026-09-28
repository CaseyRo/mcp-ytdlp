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
import threading

# Settings are read at import time (see test_download_filename.py).
os.environ.setdefault("TRANSPORT", "stdio")
os.environ.setdefault("OUTPUT_DIRECTORY", tempfile.mkdtemp(prefix="mcp_ytdlp_test_"))

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastmcp import Client  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402

from mcp_ytdlp import server  # noqa: E402
from mcp_ytdlp.server import mcp  # noqa: E402

pytestmark = pytest.mark.anyio

EXPECTED_TOOLS = {"download_video", "get_download_result", "convert_video", "cleanup_files"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_server_registers_its_tools():
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == EXPECTED_TOOLS


async def test_annotations_survive_the_wire():
    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    cleanup = tools["cleanup_files"].annotations
    assert cleanup.read_only_hint is False
    assert cleanup.destructive_hint is True
    assert tools["download_video"].annotations.open_world_hint is True
    assert tools["get_download_result"].annotations.read_only_hint is True


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


def _fake_download(tmp_output_dir, release: threading.Event | None = None):
    """subprocess.run stand-in: metadata instantly, download optionally blocked on `release`."""
    target = Path(tmp_output_dir) / "Generic-slow.mp4"

    def fake_run(cmd, *args, **kwargs):
        assert cmd[0] == "yt-dlp", f"unexpected subprocess: {cmd}"
        if "--dump-json" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout='{"id": "slow"}', stderr="")
        if release is not None:
            assert release.wait(10)
        target.write_bytes(b"\x00")
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{target}\n", stderr="")

    return fake_run


async def test_slow_download_returns_pending_then_poll_returns_result(tmp_output_dir, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(subprocess, "run", _fake_download(tmp_output_dir, release))
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)
    monkeypatch.setattr(server, "INLINE_WAIT_SECONDS", 0.2)

    async with Client(mcp) as client:
        first = (await client.call_tool("download_video", {"url": "https://example.com/v"})).structured_content["result"]
        assert first["status"] == "pending"
        assert first["poll_with"]["tool"] == "get_download_result"

        still = await client.call_tool("get_download_result", {"job_id": first["job_id"], "wait_seconds": 0})
        assert still.structured_content["result"]["status"] == "pending"

        release.set()
        monkeypatch.setattr(server, "INLINE_WAIT_SECONDS", 5)
        done = await client.call_tool("get_download_result", {"job_id": first["job_id"], "wait_seconds": 5})
    payload = done.structured_content["result"]
    assert payload["status"] == "success"
    assert payload["filename"] == "Generic-slow.mp4"


async def test_unknown_job_id_is_an_error():
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="Unknown job_id"):
            await client.call_tool("get_download_result", {"job_id": "nope", "wait_seconds": 0})


async def test_failed_pending_download_raises_on_poll(tmp_output_dir, monkeypatch):
    release = threading.Event()

    def fake_run(cmd, *args, **kwargs):
        if "--dump-json" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout='{"id": "x"}', stderr="")
        assert release.wait(10)
        raise subprocess.CalledProcessError(1, cmd, stderr="ERROR: Private video")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)
    monkeypatch.setattr(server, "INLINE_WAIT_SECONDS", 0.2)

    async with Client(mcp) as client:
        first = (await client.call_tool("download_video", {"url": "https://example.com/v"})).structured_content["result"]
        assert first["status"] == "pending"
        release.set()
        monkeypatch.setattr(server, "INLINE_WAIT_SECONDS", 5)
        with pytest.raises(ToolError, match="private"):
            await client.call_tool("get_download_result", {"job_id": first["job_id"], "wait_seconds": 5})


async def test_subprocess_timeout_is_an_error(tmp_output_dir, monkeypatch):
    seen = []

    def fake_run(cmd, *args, **kwargs):
        seen.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)
    monkeypatch.setattr(server.settings, "download_timeout_seconds", 7)

    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="timed out after 7s"):
            await client.call_tool("download_video", {"url": "https://example.com/v"})
    assert seen == [7]


@pytest.mark.parametrize("escape", ["..", "../elsewhere", "/etc", "sub/../../x"])
async def test_output_directory_escape_is_rejected(tmp_output_dir, monkeypatch, escape):
    def fail(*a, **k):
        raise AssertionError("yt-dlp must not run for a rejected output_directory")

    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)

    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="escapes"):
            await client.call_tool("download_video", {"url": "https://example.com/v", "output_directory": escape})


async def test_output_subdirectory_is_allowed(tmp_output_dir, monkeypatch):
    sub = Path(tmp_output_dir) / "clips"
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)
    fake = _fake_download(str(sub))
    monkeypatch.setattr(subprocess, "run", fake)

    async with Client(mcp) as client:
        result = await client.call_tool(
            "download_video", {"url": "https://example.com/v", "output_directory": "clips"}
        )
    assert result.structured_content["result"]["status"] == "success"


async def test_call_tool_writes_one_usage_line(capsys):
    async with Client(mcp) as client:
        await client.call_tool("cleanup_files", {"retention_days": 100000})
    lines = [line for line in capsys.readouterr().err.splitlines() if '"mcp_usage"' in line]
    assert len(lines) == 1
    assert all(s in lines[0] for s in ('"ytdlp"', '"cleanup_files"', '"outcome": "ok"'))


async def test_convert_missing_file_raises(tmp_output_dir, monkeypatch):
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="not found"):
            await client.call_tool("convert_video", {"video_filename": "nope.mp4", "target_format": "webm"})


async def test_cleanup_rejects_zero_retention():
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="at least 1"):
            await client.call_tool("cleanup_files", {"retention_days": 0})


async def test_failed_call_logs_outcome_error(capsys):
    async with Client(mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool("cleanup_files", {"retention_days": 0})
    lines = [line for line in capsys.readouterr().err.splitlines() if '"mcp_usage"' in line]
    assert len(lines) == 1
    assert '"outcome": "error"' in lines[0]
