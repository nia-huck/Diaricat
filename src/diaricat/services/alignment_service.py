"""Alignment service to fuse ASR segments and diarization turns."""

from __future__ import annotations

from diaricat.models.domain import RawTranscriptSegment, SpeakerProfile, SpeakerTurn, TranscriptSegment


class AlignmentService:
    _palette = [
        "#5B8FF9",
        "#5AD8A6",
        "#5D7092",
        "#F6BD16",
        "#E8684A",
        "#6DC8EC",
        "#9270CA",
        "#FF9D4D",
    ]

    @staticmethod
    def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
        return max(0.0, min(a_end, b_end) - max(a_start, b_start))

    @staticmethod
    def _nearest_speaker(segment_start: float, segment_end: float, turns: list[SpeakerTurn]) -> str:
        if not turns:
            return "SPEAKER_UNK"
        center = (segment_start + segment_end) / 2.0
        nearest = min(turns, key=lambda turn: abs(((turn.start + turn.end) / 2.0) - center))
        return nearest.speaker_id

    @staticmethod
    def _split_words_by_weights(text: str, weights: list[float]) -> list[str]:
        words = [w for w in text.split() if w]
        if not words or not weights:
            return [text.strip()]
        if len(weights) == 1:
            return [" ".join(words)]

        total_weight = max(sum(weights), 1e-6)
        target_counts = [max(1, int(round(len(words) * (w / total_weight)))) for w in weights]

        # Reconcile rounding so total equals number of words.
        diff = sum(target_counts) - len(words)
        while diff > 0:
            idx = max(range(len(target_counts)), key=lambda i: target_counts[i])
            if target_counts[idx] > 1:
                target_counts[idx] -= 1
                diff -= 1
            else:
                break
        while diff < 0:
            idx = max(range(len(target_counts)), key=lambda i: weights[i])
            target_counts[idx] += 1
            diff += 1

        chunks: list[str] = []
        cursor = 0
        for count in target_counts:
            end = min(cursor + count, len(words))
            chunks.append(" ".join(words[cursor:end]).strip())
            cursor = end
        if cursor < len(words):
            chunks[-1] = (chunks[-1] + " " + " ".join(words[cursor:])).strip()
        return [chunk for chunk in chunks if chunk]

    def align(
        self,
        asr_segments: list[RawTranscriptSegment],
        speaker_turns: list[SpeakerTurn],
    ) -> list[TranscriptSegment]:
        output: list[TranscriptSegment] = []
        if not speaker_turns:
            for segment in asr_segments:
                output.append(
                    TranscriptSegment(
                        start=segment.start, end=segment.end,
                        speaker_id="SPEAKER_UNK", speaker_name="Desconocido",
                        text_raw=segment.text,
                    )
                )
            return output

        sorted_turns = sorted(speaker_turns, key=lambda t: t.start)

        for segment in asr_segments:
            overlap_turns: list[tuple[SpeakerTurn, float, float, float]] = []
            for turn in sorted_turns:
                if turn.end <= segment.start:
                    continue
                if turn.start >= segment.end:
                    break
                start = max(segment.start, turn.start)
                end = min(segment.end, turn.end)
                overlap = max(0.0, end - start)
                if overlap > 0.0:
                    overlap_turns.append((turn, start, end, overlap))

            if not overlap_turns:
                best_speaker = self._nearest_speaker(segment.start, segment.end, sorted_turns)
                speaker_name = best_speaker if best_speaker != "SPEAKER_UNK" else "Desconocido"
                output.append(
                    TranscriptSegment(
                        start=segment.start,
                        end=segment.end,
                        speaker_id=best_speaker,
                        speaker_name=speaker_name,
                        text_raw=segment.text,
                    )
                )
                continue

            overlap_turns.sort(key=lambda item: item[1])
            if len(overlap_turns) == 1 or len(segment.text.split()) < 3:
                turn, start, end, _ = overlap_turns[0]
                output.append(
                    TranscriptSegment(
                        start=start,
                        end=end,
                        speaker_id=turn.speaker_id,
                        speaker_name=turn.speaker_id,
                        text_raw=segment.text,
                    )
                )
                continue

            weights = [item[3] for item in overlap_turns]
            text_parts = self._split_words_by_weights(segment.text, weights)
            if len(text_parts) != len(overlap_turns):
                text_parts = [segment.text] + [""] * (len(overlap_turns) - 1)

            for part, (turn, start, end, _) in zip(text_parts, overlap_turns, strict=False):
                if not part.strip():
                    continue
                output.append(
                    TranscriptSegment(
                        start=start,
                        end=end,
                        speaker_id=turn.speaker_id,
                        speaker_name=turn.speaker_id,
                        text_raw=part.strip(),
                    )
                )

        return output

    def build_speaker_profiles(self, segments: list[TranscriptSegment]) -> list[SpeakerProfile]:
        seen: dict[str, SpeakerProfile] = {}
        for segment in segments:
            if segment.speaker_id in seen:
                continue
            color = self._palette[len(seen) % len(self._palette)]
            seen[segment.speaker_id] = SpeakerProfile(
                speaker_id=segment.speaker_id,
                custom_name=segment.speaker_name,
                color_ui=color,
            )
        return list(seen.values())
