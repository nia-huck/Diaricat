from __future__ import annotations

from diaricat.models.domain import RawTranscriptSegment, SpeakerTurn
from diaricat.services.alignment_service import AlignmentService


def test_alignment_uses_max_overlap() -> None:
    service = AlignmentService()
    asr = [
        RawTranscriptSegment(start=0.0, end=2.0, text="hola"),
        RawTranscriptSegment(start=2.0, end=4.0, text="mundo"),
    ]
    turns = [
        SpeakerTurn(start=0.0, end=1.0, speaker_id="SPEAKER_00"),
        SpeakerTurn(start=1.0, end=4.0, speaker_id="SPEAKER_01"),
    ]

    output = service.align(asr, turns)

    assert output[0].speaker_id == "SPEAKER_00"
    assert output[1].speaker_id == "SPEAKER_01"


def test_alignment_without_overlap_uses_nearest_turn() -> None:
    service = AlignmentService()
    asr = [RawTranscriptSegment(start=10.0, end=12.0, text="sin match")]
    turns = [
        SpeakerTurn(start=0.0, end=1.0, speaker_id="SPEAKER_00"),
        SpeakerTurn(start=14.0, end=16.0, speaker_id="SPEAKER_01"),
    ]

    output = service.align(asr, turns)

    assert output[0].speaker_id == "SPEAKER_01"
