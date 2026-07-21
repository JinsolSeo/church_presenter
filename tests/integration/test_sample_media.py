from __future__ import annotations

import json
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "sample_assets"


def test_generated_audio_samples_and_playlist_are_consistent() -> None:
    expected_seconds = (5, 7, 9)
    tracks = sorted((SAMPLES / "audio").glob("sample_track_*.wav"))
    assert len(tracks) == 3
    for path, seconds in zip(tracks, expected_seconds, strict=True):
        with wave.open(str(path), "rb") as stream:
            assert stream.getnchannels() == 1
            assert stream.getframerate() == 44_100
            assert abs(stream.getnframes() / stream.getframerate() - seconds) < 0.01
    playlist_path = SAMPLES / "playlists" / "sample_playlist.json"
    data = json.loads(playlist_path.read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert len(data["items"]) == 3
    for item in data["items"]:
        assert item["source_type"] == "local_file"
        assert (playlist_path.parent / item["source"]).resolve().is_file()


def test_generated_video_is_a_nonempty_mp4() -> None:
    path = SAMPLES / "videos" / "sample_video.mp4"
    assert path.stat().st_size > 100_000
    data = path.read_bytes()
    header = data[:32]
    assert b"ftyp" in header
    marker = data.index(b"mvhd") + 4
    version = data[marker]
    if version == 0:
        timescale = int.from_bytes(data[marker + 12 : marker + 16], "big")
        duration = int.from_bytes(data[marker + 16 : marker + 20], "big")
    else:
        timescale = int.from_bytes(data[marker + 20 : marker + 24], "big")
        duration = int.from_bytes(data[marker + 24 : marker + 32], "big")
    assert duration / timescale >= 10
