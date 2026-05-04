"""Regression tests for the download_video filename-resolution bug.

Bug summary: when yt-dlp's download silently no-ops (signed-URL format
mismatch, partial fail with exit 0, etc.) and creates no new file, the
old code picked the *most-recently-modified* file in the output dir,
returning a stale unrelated download as the "successful" result. With
two consecutive different URLs that pattern returned the SAME bytes
for both calls.

The fix introduces two layered detection mechanisms:
  1. Trust ``--print after_move:filepath`` from yt-dlp's stdout.
  2. Fall back to a before/after directory snapshot diff.
  3. Raise loudly when neither finds a new file.
"""

from __future__ import annotations

import os

# Settings construction happens at import time and requires MCP_API_KEY
# unless TRANSPORT=stdio. Server import also mkdir()s OUTPUT_DIRECTORY.
# Set both before the import below.
os.environ.setdefault("TRANSPORT", "stdio")
import tempfile  # noqa: E402

_TEST_OUTDIR = tempfile.mkdtemp(prefix="mcp_ytdlp_test_")
os.environ.setdefault("OUTPUT_DIRECTORY", _TEST_OUTDIR)

import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from mcp_ytdlp import server  # noqa: E402


@pytest.fixture
def fake_metadata():
    """Minimal yt-dlp metadata-extraction stdout for a generic URL."""

    return (
        '{"id": "AQNFreshId", "title": "fresh", "ext": "mp4", '
        '"webpage_url": "https://cdn.example/v.mp4"}'
    )


def _make_completed(stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_filename_from_after_move_print(tmp_output_dir, clean_env, monkeypatch, fake_metadata):
    """When yt-dlp prints ``after_move:filepath``, we trust that path."""
    out_dir = Path(tmp_output_dir)
    expected = out_dir / "Generic-AQNFreshId.mp4"
    expected.write_bytes(b"\x00\x00\x00\x18ftypmp42")  # minimal mp4 magic

    monkeypatch.setenv("OUTPUT_DIRECTORY", tmp_output_dir)

    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        if "--dump-json" in cmd:
            return _make_completed(stdout=fake_metadata)
        # download command — print the filepath as yt-dlp would
        return _make_completed(stdout=str(expected) + "\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)

    res = server.download_video(url="https://cdn.example/AQNFreshId.mp4?token=x")
    assert res["status"] == "success"
    assert res["filename"] == "Generic-AQNFreshId.mp4"
    # And the download command must have included the after_move flag
    download_cmd = calls[-1]
    assert "--print" in download_cmd and "after_move:filepath" in download_cmd


def test_filename_from_snapshot_diff(tmp_output_dir, clean_env, monkeypatch, fake_metadata):
    """If --print is absent (older yt-dlp), find the file that's new."""
    out_dir = Path(tmp_output_dir)
    # Pre-existing stale file from a previous call
    stale = out_dir / "Generic-StaleId.mp4"
    stale.write_bytes(b"\x00" * 100)

    fresh = out_dir / "Generic-AQNFreshId.mp4"

    monkeypatch.setenv("OUTPUT_DIRECTORY", tmp_output_dir)

    def fake_run(cmd, *args, **kwargs):
        if "--dump-json" in cmd:
            return _make_completed(stdout=fake_metadata)
        # Older yt-dlp ignores --print. Simulate by writing a new file
        # but emitting empty stdout so the after_move branch finds nothing.
        fresh.write_bytes(b"\x00\x00\x00\x18ftypmp42new")
        return _make_completed(stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)

    res = server.download_video(url="https://cdn.example/AQNFreshId.mp4?token=x")
    assert res["status"] == "success"
    assert res["filename"] == "Generic-AQNFreshId.mp4"
    # Snapshot diff explicitly excluded the stale neighbor:
    assert res["filename"] != "Generic-StaleId.mp4"


def test_no_new_file_raises_loudly(tmp_output_dir, clean_env, monkeypatch, fake_metadata):
    """When yt-dlp exits 0 without producing a new file, fail —
    never return a stale neighbor as if the download succeeded."""
    out_dir = Path(tmp_output_dir)
    stale = out_dir / "Generic-StaleId.mp4"
    stale.write_bytes(b"\x00" * 100)

    monkeypatch.setenv("OUTPUT_DIRECTORY", tmp_output_dir)

    def fake_run(cmd, *args, **kwargs):
        if "--dump-json" in cmd:
            return _make_completed(stdout=fake_metadata)
        # Download "succeeded" but produced no new file (silent no-op).
        return _make_completed(stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)

    res = server.download_video(url="https://cdn.example/AQNFreshId.mp4?token=x")
    # The function returns an error response (CalledProcessError handler),
    # NOT a success response pointing at the stale file.
    assert res["status"] == "error"
    assert "stale" not in res["filename"] if "filename" in res else True


def test_two_consecutive_calls_return_their_own_files(
    tmp_output_dir, clean_env, monkeypatch, fake_metadata
):
    """The original bug: two consecutive different-URL calls returned
    the SAME filename (the first download's). After the fix, each call
    must return its own file."""
    out_dir = Path(tmp_output_dir)
    monkeypatch.setenv("OUTPUT_DIRECTORY", tmp_output_dir)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_output_dir)

    state = {"first_done": False}

    def fake_run(cmd, *args, **kwargs):
        if "--dump-json" in cmd:
            mid = "First" if not state["first_done"] else "Second"
            return _make_completed(
                stdout=(
                    f'{{"id": "Mid{mid}", "title": "{mid.lower()}", '
                    f'"ext": "mp4", "webpage_url": "https://cdn.example"}}'
                )
            )
        # Download — write a unique file per call
        target = out_dir / (
            "Generic-MidFirst.mp4" if not state["first_done"] else "Generic-MidSecond.mp4"
        )
        target.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"a" if not state["first_done"] else b"b") * 32)
        out = str(target) + "\n"
        state["first_done"] = True
        return _make_completed(stdout=out)

    monkeypatch.setattr(subprocess, "run", fake_run)

    res1 = server.download_video(url="https://cdn.example/first.mp4?token=x")
    res2 = server.download_video(url="https://cdn.example/second.mp4?token=y")

    assert res1["status"] == "success"
    assert res2["status"] == "success"
    assert res1["filename"] == "Generic-MidFirst.mp4"
    assert res2["filename"] == "Generic-MidSecond.mp4"
    assert res1["filename"] != res2["filename"]
