from __future__ import annotations

import json
from pathlib import Path

import pytest

from church_presenter.domain.song import SongCue, SongDocument, SongPlanEntry
from church_presenter.services.song_service import load_song, load_song_plan, save_song_plan

SAMPLE_SONGS = Path(__file__).parents[2] / "sample_assets" / "songs"


def test_sample_song_json_files_are_valid_and_sectioned() -> None:
    paths = sorted(SAMPLE_SONGS.glob("*.json"))

    assert len(paths) == 4
    songs = [load_song(path) for path in paths]
    assert {song.id for song in songs} == {
        "grace_morning",
        "joyful_song",
        "prayer_confession",
        "together_praise",
    }
    assert all(song.section(song.default_sequence[0]).lines for song in songs)
    assert songs[0].default_sequence.count("chorus") == 3


def test_song_rejects_unknown_default_sequence_section() -> None:
    payload = json.loads((SAMPLE_SONGS / "01_grace_morning.json").read_text(encoding="utf-8"))
    payload["default_sequence"].append("outro")

    with pytest.raises(ValueError, match="unknown sections"):
        SongDocument.from_dict(payload)


def test_song_plan_round_trip_keeps_repeated_sections_without_embedding_lyrics(
    tmp_path: Path,
) -> None:
    song_path = SAMPLE_SONGS / "01_grace_morning.json"
    song = load_song(song_path)
    entry = SongPlanEntry.create(song_path, song, song.default_sequence)
    plan_path = tmp_path / "이번주_찬양_콘티.json"

    save_song_plan(plan_path, [entry])
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    restored = load_song_plan(plan_path)

    assert payload["document_type"] == "church_presenter_song_plan"
    assert payload["entries"][0]["sequence"] == list(song.default_sequence)
    assert "lines" not in payload["entries"][0]
    assert restored[0].entry_id == entry.entry_id
    assert restored[0].song == song
    assert restored[0].sequence == song.default_sequence


def test_song_cue_reference_uses_semantic_entry_occurrence_and_line() -> None:
    cue = SongCue("entry123", 4, "chorus", 2, 4, "첫 줄\n둘째 줄")

    assert cue.reference == "song:entry123:4:2"
    assert SongCue.parse_reference(cue.reference) == ("entry123", 4, 2)
