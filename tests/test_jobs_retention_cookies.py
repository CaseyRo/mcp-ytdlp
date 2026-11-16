"""Jobs survive restarts, retention sweeps the output dir only, server cookies win (COS-181)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time

# Settings are read at import time (see test_download_filename.py).
os.environ.setdefault("TRANSPORT", "stdio")
os.environ.setdefault("OUTPUT_DIRECTORY", tempfile.mkdtemp(prefix="mcp_ytdlp_test_"))

from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_ytdlp import server
from mcp_ytdlp.server import mcp


@pytest.fixture
def anyio_backend():
    return "asyncio"


# --- jobs survive restarts -------------------------------------------------


@pytest.mark.anyio
async def test_finished_job_is_read_back_after_restart(tmp_output_dir, monkeypatch):
    release = threading.Event()
    target = Path(tmp_output_dir) / "Generic-slow.mp4"

    def fake_run(cmd, *args, **kwargs):
        if "--dump-json" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout='{"id": "slow", "title": "t"}', stderr="")
        assert release.wait(10)
        target.write_bytes(b"\x00")
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{target}\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)
    monkeypatch.setattr(server, "INLINE_WAIT_SECONDS", 0.2)

    async with Client(mcp) as client:
        first = (await client.call_tool("download_video", {"url": "https://example.com/v"})).structured_content["result"]
        job_id = first["job_id"]
        record = Path(tmp_output_dir) / ".jobs" / f"{job_id}.json"
        assert '"running"' in record.read_text()

        release.set()
        server._jobs[job_id].result(timeout=10)
        assert '"success"' in record.read_text()

        monkeypatch.setattr(server, "_jobs", {})  # restart: in-memory futures are gone
        done = await client.call_tool("get_download_result", {"job_id": job_id, "wait_seconds": 0})
    payload = done.structured_content["result"]
    assert payload["status"] == "success"
    assert payload["filename"] == "Generic-slow.mp4"
    assert payload["metadata"]["title"] == "t"


@pytest.mark.anyio
async def test_failed_job_is_still_an_error_after_restart(tmp_output_dir, monkeypatch):
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)
    job_id = "b" * 32
    server._save_job(job_id, "2026-11-16T00:00:00+00:00", "error", error="Video is private: nope")
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="Video is private"):
            await client.call_tool("get_download_result", {"job_id": job_id, "wait_seconds": 0})


@pytest.mark.anyio
async def test_job_running_at_restart_is_reported_interrupted(tmp_output_dir, monkeypatch):
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)
    job_id = "a" * 32
    server._save_job(job_id, "2026-11-16T00:00:00+00:00", "running")
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="interrupted by a restart, start the download again"):
            await client.call_tool("get_download_result", {"job_id": job_id, "wait_seconds": 0})


@pytest.mark.anyio
@pytest.mark.parametrize("job_id", ["../../etc/passwd", "A" * 32, "a" * 31])
async def test_malformed_job_id_never_touches_the_filesystem(job_id):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="Unknown job_id"):
            await client.call_tool("get_download_result", {"job_id": job_id, "wait_seconds": 0})


# --- retention -------------------------------------------------------------


def test_retention_deletes_old_downloads_and_records_only(tmp_output_dir, monkeypatch):
    root = Path(tmp_output_dir) / "out"
    outside = Path(tmp_output_dir) / "outside"
    (root / ".jobs").mkdir(parents=True)
    (root / "clips").mkdir()
    outside.mkdir()
    (root / "linked").symlink_to(outside)  # must not be followed

    old = [root / "old.mp4", root / "old.mp4.part", root / "clips" / "old.webm", root / ".jobs" / ("c" * 32 + ".json"),
           root / "old.mp3", root / "Generic-asset.jpg"]
    keep_old = [root / "yt-cookies.txt", root / "notes.txt", outside / "elsewhere.mp4"]
    for p in keep_old + old:
        p.write_bytes(b"x")
    time.sleep(0.05)
    new = [root / "new.mp4", root / ".jobs" / ("d" * 32 + ".json")]
    for p in new:
        p.write_bytes(b"x")

    # One day after the old files: they are past a 1-day window, the new ones are not.
    boundary = (max(p.stat().st_ctime for p in old + keep_old) + min(p.stat().st_ctime for p in new)) / 2
    monkeypatch.setattr(server, "OUTPUT_DIR", str(root))
    monkeypatch.setattr(server.time, "time", lambda: boundary + 86400)

    deleted = server.cleanup_old_files(1)

    assert deleted == 3  # downloads only; the job record is not counted
    assert not any(p.exists() for p in old)
    assert all(p.exists() for p in new + keep_old)


def test_periodic_sweep_survives_an_error(monkeypatch):
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("disk on fire")

    def stop_after_first_sleep(_seconds):
        raise SystemExit

    monkeypatch.setattr(server, "cleanup_old_files", boom)
    monkeypatch.setattr(server.time, "sleep", stop_after_first_sleep)
    with pytest.raises(SystemExit):
        server.run_cleanup_periodically()
    assert calls == [1]  # swept at once (startup), error swallowed, then slept


# --- cookies precedence ----------------------------------------------------


def _capture_cookies(tmp_output_dir, monkeypatch):
    """Fake yt-dlp that records the content of whatever --cookies file it is given."""
    seen: list[str | None] = []
    target = Path(tmp_output_dir) / "Generic-c.mp4"

    def fake_run(cmd, *args, **kwargs):
        cookies = cmd[cmd.index("--cookies") + 1] if "--cookies" in cmd else None
        seen.append(Path(cookies).read_text() if cookies else None)
        if "--dump-json" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout='{"id": "c"}', stderr="")
        if cookies:
            Path(cookies).write_text("rewritten by yt-dlp")  # yt-dlp saves the jar back
        target.write_bytes(b"\x00")
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{target}\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)
    return seen


def test_env_cookies_win_over_argument_and_stay_untouched(tmp_output_dir, monkeypatch):
    seen = _capture_cookies(tmp_output_dir, monkeypatch)
    secret = Path(tmp_output_dir) / "secrets" / "yt-cookies.txt"
    secret.parent.mkdir()
    secret.write_text("ENV")
    (Path(tmp_output_dir) / "arg.txt").write_text("ARG")
    monkeypatch.setattr(server.settings, "ytdlp_cookies_file", str(secret))
    before = set(Path(tempfile.gettempdir()).glob("yt-cookies-*"))

    res = server._run_download("https://example.com/v", cookies_file="arg.txt")

    assert res["status"] == "success"
    assert seen == ["ENV", "ENV"]  # metadata and download both used the server cookies
    assert secret.read_text() == "ENV"  # yt-dlp wrote to a copy, not the secret
    assert set(Path(tempfile.gettempdir()).glob("yt-cookies-*")) == before  # copy removed


def test_env_cookies_used_without_argument(tmp_output_dir, monkeypatch):
    seen = _capture_cookies(tmp_output_dir, monkeypatch)
    secret = Path(tmp_output_dir) / "yt.txt"
    secret.write_text("ENV")
    monkeypatch.setattr(server.settings, "ytdlp_cookies_file", str(secret))

    server._run_download("https://example.com/v")
    assert seen == ["ENV", "ENV"]


def test_argument_cookies_used_when_env_file_missing(tmp_output_dir, monkeypatch):
    seen = _capture_cookies(tmp_output_dir, monkeypatch)
    (Path(tmp_output_dir) / "arg.txt").write_text("ARG")
    monkeypatch.setattr(server.settings, "ytdlp_cookies_file", str(Path(tmp_output_dir) / "missing.txt"))

    server._run_download("https://example.com/v", cookies_file="arg.txt")
    assert seen == ["ARG", "ARG"]
    # Old behaviour unchanged: yt-dlp gets the output-dir file itself, not a copy.
    assert (Path(tmp_output_dir) / "arg.txt").read_text() == "rewritten by yt-dlp"


def test_no_cookies_when_neither_is_set(tmp_output_dir, monkeypatch):
    seen = _capture_cookies(tmp_output_dir, monkeypatch)
    monkeypatch.setattr(server.settings, "ytdlp_cookies_file", "")

    server._run_download("https://example.com/v")
    assert seen == [None, None]
