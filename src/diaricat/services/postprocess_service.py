"""Conservative post-processing (correction + summary) with llama.cpp fallback."""

from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from diaricat.errors import DiaricatError, ErrorCode
from diaricat.models.domain import SummaryDocument, TranscriptSegment
from diaricat.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class PostprocessContext:
    project_id: str | None = None
    language_hint: str = "auto"
    speaker_id: str | None = None
    speaker_context: str | None = None


class LocalPostprocessService:
    _COMMON_ASR_FIXES: tuple[tuple[str, str], ...] = (
        (r"\b(tenia|tenía)\s+(?:tu|tú|su|mi)\s+todo\b", r"\1 todo"),
        (r"\bo\s+que\s+te\s+separ(?:ar|a?r)\b", "o queres esperar"),
        (r"\bcartas\s+documentos\b", "cartas documento"),
    )
    _LOW_VALUE_PATTERNS: tuple[str, ...] = (
        r"^se escucha\??$",
        r"^ahi esta\.?$",
        r"^como estas\??$",
        r"^bueno[, ]*ok\.?$",
        r"^hola\.?$",
    )
    _SUMMARY_KEYWORDS: tuple[str, ...] = (
        "licencia",
        "carta documento",
        "carta",
        "documento",
        "reunion",
        "viernes",
        "empresa",
        "despido",
        "despida",
        "enviar",
        "enviadas",
        "esperar",
        "antes",
        "contactaron",
    )
    _DECISION_MARKERS: tuple[str, ...] = (
        "decid",
        "acord",
        "aprob",
        "enviar",
        "enviad",
        "antes",
        "esperar",
        "quieres",
        "queres",
        "viernes",
        "despid",
        "hacer",
    )
    _LEXICAL_FIXES: tuple[tuple[str, str], ...] = (
        (r"\bcartocumento[s]?\b", "carta documento"),
        (r"\baperito\b", "perito"),
        (r"\btestiguar\b", "testificar"),
        (r"\bacumento\b", "documento"),
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._llm: object | None = None
        self._llm_lock = threading.Lock()

    def _load_llm(self) -> object | None:
        with self._llm_lock:
            if self._llm is not None:
                return self._llm

            configured_path = str(self.settings.services.llama_model_path or "").strip()
            if not configured_path:
                logger.info("Postprocess LLM disabled: no llama_model_path configured.")
                return None
            model_path = Path(configured_path).expanduser()
            if not model_path.is_absolute():
                model_path = self.settings.app.workspace_dir / model_path

            if not model_path.exists():
                models_dir = self.settings.app.workspace_dir / "models"
                stem_prefix = Path(configured_path).stem.split("-q", maxsplit=1)[0]
                if stem_prefix:
                    candidates = sorted(models_dir.glob(f"{stem_prefix}*.gguf"))
                    if candidates:
                        model_path = candidates[0]

            if not model_path.exists():
                logger.warning(
                    "Postprocess LLM model path does not exist; using rule-based fallback.",
                    extra={"ctx_model_path": str(model_path)},
                )
                return None

            try:
                from llama_cpp import Llama  # type: ignore

                self._llm = Llama(
                    model_path=str(model_path),
                    n_ctx=self.settings.services.llama_n_ctx,
                    n_threads=self.settings.services.llama_n_threads,
                    verbose=False,
                )
                logger.info(
                    "Postprocess LLM initialized.",
                    extra={
                        "ctx_model_path": str(model_path),
                        "ctx_llama_n_ctx": self.settings.services.llama_n_ctx,
                        "ctx_llama_n_threads": self.settings.services.llama_n_threads,
                    },
                )
                return self._llm
            except Exception as exc:
                logger.warning(
                    "Postprocess LLM initialization failed; using rule-based fallback.",
                    extra={"ctx_error": str(exc), "ctx_model_path": str(model_path)},
                )
                return None

    def _generate(self, prompt: str, max_tokens: int = 300, language: str = "es") -> str | None:
        llm = self._load_llm()
        if llm is None:
            return None
        try:
            system_msg = (
                "You are an expert assistant for audio transcription processing."
                if language.startswith("en")
                else "Eres un asistente experto en transcripciones de audio en español."
            )
            response = llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.1,
                top_p=0.9,
            )
            choices = response.get("choices", [])
            if not choices:
                return None
            message = choices[0].get("message", {})
            return str(message.get("content", "")).strip()
        except Exception as exc:
            logger.warning(
                "LLM generation failed, falling back to rule-based.",
                extra={"ctx_error": str(exc), "ctx_prompt_length": len(prompt)},
            )
            return None

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        value = re.sub(r"\s+", " ", text)
        value = re.sub(r"\.\s*\.\s*\.", "...", value)
        value = re.sub(r"\s+([,.;:!?])", r"\1", value)
        value = re.sub(r"([,;:!?])([^\s])", r"\1 \2", value)
        value = re.sub(r"(?<!\.)\.([^\s.\d])", r". \1", value)
        return value.strip()

    @staticmethod
    def _strip_accents(text: str) -> str:
        normalized = unicodedata.normalize("NFD", text)
        return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")

    @staticmethod
    def _ensure_terminal_punctuation(text: str) -> str:
        if not text:
            return text
        if text[-1] in ".!?":
            return text
        return f"{text}."

    @staticmethod
    def _fix_symbols(text: str) -> str:
        fixed = text
        fixed = re.sub(r"(^|[.!?]\s+|[\(\[\{])ż(?=[A-Za-zÁÉÍÓÚáéíóúÑñ])", r"\1¿", fixed)
        fixed = fixed.replace("Ż", "¿")
        fixed = re.sub(r"\.\s+\.\s+", "... ", fixed)
        fixed = re.sub(r"\.\s+\.$", "...", fixed)
        return fixed

    def _shorten_sentence(self, text: str, max_chars: int = 220) -> str:
        sentence = self._normalize_whitespace(text)
        if len(sentence) <= max_chars:
            return self._ensure_terminal_punctuation(sentence)

        parts = [part.strip() for part in sentence.split(",") if part.strip()]
        if not parts:
            return self._ensure_terminal_punctuation(sentence[: max_chars - 3].rstrip() + "...")

        compact = parts[0]
        for part in parts[1:]:
            candidate = f"{compact}, {part}"
            if len(candidate) > max_chars - 3:
                break
            compact = candidate

        if len(compact) >= len(sentence):
            compact = sentence[: max_chars - 3].rstrip()
        compact = compact.rstrip(" ,;:.")
        return self._ensure_terminal_punctuation(compact + "...")

    def _guardrail(self, original: str, candidate: str) -> str:
        if not candidate.strip():
            return original

        ratio = SequenceMatcher(None, original, candidate).ratio()
        length_delta = abs(len(candidate) - len(original)) / max(len(original), 1)

        if ratio < self.settings.services.correction_ratio_threshold:
            return original
        if length_delta > self.settings.services.correction_max_length_delta:
            return original
        return candidate.strip()

    def _rule_based_correct(self, text: str) -> str:
        corrected = self._fix_symbols(text)
        corrected = self._normalize_whitespace(corrected)
        corrected = re.sub(r"\b(\w+)\s+\1\b", r"\1", corrected, flags=re.IGNORECASE)
        corrected = re.sub(r"\btu\s+todo\b", "todo", corrected, flags=re.IGNORECASE)

        for pattern, replacement in self._COMMON_ASR_FIXES:
            corrected = re.sub(pattern, replacement, corrected, flags=re.IGNORECASE)
        for pattern, replacement in self._LEXICAL_FIXES:
            corrected = re.sub(pattern, replacement, corrected, flags=re.IGNORECASE)

        corrected = re.sub(r"\s+,", ",", corrected)
        corrected = re.sub(r",\s*,", ", ", corrected)
        corrected = re.sub(r"\b(obvio)(?:,\s*\1){1,}\b", r"\1", corrected, flags=re.IGNORECASE)
        corrected = re.sub(r"\s{2,}", " ", corrected).strip()
        return corrected

    def correct(self, text: str, context: PostprocessContext | None = None) -> str:
        original = self._rule_based_correct(text)
        lang = (context.language_hint if context else "auto").lower()
        is_english = lang.startswith("en")
        context_block = ""
        if context is not None and context.speaker_context:
            speaker = context.speaker_id or ("speaker" if is_english else "hablante")
            context_block = (
                f"Conversation context ({speaker}):\n{context.speaker_context}\n\n"
                if is_english
                else f"Contexto de la conversación ({speaker}):\n{context.speaker_context}\n\n"
            )

        if is_english:
            prompt = (
                "You are a conservative audio transcription corrector.\n"
                "Rules:\n"
                "1) Keep the facts unchanged.\n"
                "2) Do not add entities, details, or interpretations.\n"
                "3) Only correct punctuation, spacing, and obvious ASR errors.\n"
                "Return only the corrected text, no explanations.\n\n"
                f"{context_block}"
                f"Text:\n{original}\n"
            )
        else:
            prompt = (
                "Eres un corrector conservador de transcripciones de audio.\n"
                "Reglas:\n"
                "1) Mantene los hechos sin cambios.\n"
                "2) No agregues entidades, detalles ni interpretaciones.\n"
                "3) Solo corregí puntuación, espacios y errores obvios de transcripción automática.\n"
                "Devolvé únicamente el texto corregido, sin explicaciones.\n\n"
                f"{context_block}"
                f"Texto:\n{original}\n"
            )
        candidate = self._generate(prompt, max_tokens=500, language=lang)
        if candidate is None:
            logger.debug("Correction fallback to rule-based output (LLM unavailable).")
            return original

        candidate = self._rule_based_correct(candidate)
        guarded = self._guardrail(original, candidate)
        if guarded == original and candidate.strip() != original.strip():
            logger.debug(
                "Correction candidate rejected by guardrail.",
                extra={
                    "ctx_original_len": len(original),
                    "ctx_candidate_len": len(candidate),
                },
            )
        return guarded

    def _split_sentences(self, text: str) -> list[str]:
        clean = re.sub(r"\s+", " ", text).strip()
        if not clean:
            return []

        by_marks = [p.strip() for p in re.split(r"(?<=[.!?])\s+", clean) if p.strip()]
        if len(by_marks) > 1:
            return by_marks

        return [p.strip() for p in re.split(r"\s*,\s+", clean) if p.strip()]

    def _normalize_for_match(self, text: str) -> str:
        value = self._strip_accents(text.lower())
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _is_low_value_sentence(self, sentence: str) -> bool:
        normalized = self._normalize_for_match(sentence.strip(" .,!?:;"))
        if len(normalized.split()) < 3:
            return True
        return any(re.fullmatch(pattern, normalized) for pattern in self._LOW_VALUE_PATTERNS)

    def _sentence_score(self, sentence: str) -> float:
        normalized = self._normalize_for_match(sentence)
        words = re.findall(r"[a-z0-9]+", normalized)
        if len(words) < 3:
            return 0.0

        score = min(len(words), 28) / 28.0
        for keyword in self._SUMMARY_KEYWORDS:
            if keyword in normalized:
                score += 1.1
        if "?" in sentence:
            score += 0.2
        if "," in sentence:
            score += 0.1
        return score

    def _extract_topics(self, sentences: list[str]) -> list[str]:
        normalized_sentences = [self._normalize_for_match(s) for s in sentences]
        topics: list[str] = []

        rules = (
            (r"carta[s]?\s+documento", "Cartas documento"),
            (r"reunion|viernes", "Reunion del viernes"),
            (r"licencia", "Licencia"),
            (r"despido|despida", "Riesgo de despido"),
            (r"empresa", "Contacto con empresa"),
            (r"enviar|enviad", "Envio de documentacion"),
        )

        for pattern, topic in rules:
            if any(re.search(pattern, sentence) for sentence in normalized_sentences):
                topics.append(topic)

        if topics:
            return topics[:5]

        fallback_topics: list[str] = []
        for sentence in sentences:
            words = [w.strip(".,;:!?()[]{}\"'") for w in sentence.split() if w.strip(".,;:!?()[]{}\"'")]
            if len(words) < 3:
                continue
            topic = " ".join(words[:4])
            if topic not in fallback_topics:
                fallback_topics.append(topic)
            if len(fallback_topics) >= 5:
                break
        return fallback_topics

    def _fallback_summary(self, text: str) -> SummaryDocument:
        sentences = self._split_sentences(text)
        if not sentences:
            return SummaryDocument()

        informative = [s for s in sentences if not self._is_low_value_sentence(s)]
        pool = informative or sentences

        ranked = sorted(pool, key=self._sentence_score, reverse=True)
        key_points: list[str] = []
        seen: set[str] = set()
        for sentence in ranked:
            normalized = self._normalize_for_match(sentence)
            if normalized in seen:
                continue
            seen.add(normalized)
            key_points.append(self._shorten_sentence(sentence))
            if len(key_points) >= 5:
                break

        decisions: list[str] = []
        for sentence in pool:
            normalized = self._normalize_for_match(sentence)
            if any(marker in normalized for marker in self._DECISION_MARKERS):
                item = self._shorten_sentence(sentence)
                if item not in decisions:
                    decisions.append(item)
            if len(decisions) >= 4:
                break

        topics = self._extract_topics(key_points or pool)
        overview = ""
        if decisions:
            overview = decisions[0]
        elif key_points:
            overview = key_points[0]
        if topics:
            topics_text = ", ".join(topics[:3]).lower()
            overview = f"La conversacion se centra en {topics_text}. {overview}".strip()

        return SummaryDocument(
            overview=overview,
            key_points=key_points,
            decisions=decisions,
            topics=topics,
            citations=None,
        )

    def _summary_needs_fallback(self, summary: SummaryDocument) -> bool:
        if not summary.key_points:
            return True
        if all(self._is_low_value_sentence(item) for item in summary.key_points):
            return True
        if not summary.overview.strip():
            return True
        return False

    @staticmethod
    def _strip_chunk_markers(text: str) -> str:
        """Remove template markers like '[Chunk 1]', 'Overview:', 'Decision:' from text."""
        cleaned = re.sub(r"\[Chunk\s*\d+\]\s*", "", text)
        cleaned = re.sub(r"^(Overview|Decision|Resumen|Punto clave)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    @staticmethod
    def _summary_prompt(text: str, language: str = "es") -> str:
        if language.startswith("en"):
            return (
                "Summarize the following meeting transcript as strict JSON with these keys:\n"
                "overview (string), key_points (array of strings), decisions (array of strings), topics (array of strings).\n"
                "Do not invent facts or fabricate people, dates, or actions not in the text.\n"
                "Respond only with the JSON, no explanations.\n\n"
                f"Transcript:\n{text}\n"
            )
        return (
            "Resumí la siguiente transcripción de reunión en JSON estricto con las siguientes claves:\n"
            "overview (string), key_points (array de strings), decisions (array de strings), topics (array de strings).\n"
            "No inventes hechos ni fabrices personas, fechas o acciones que no aparezcan en el texto.\n"
            "Respondé solo con el JSON, sin explicaciones.\n\n"
            f"Transcripción:\n{text}\n"
        )

    @staticmethod
    def _coerce_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned

    def _summary_from_raw(self, raw: str, source_text: str) -> SummaryDocument:
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1:
                return self._fallback_summary(source_text)
            payload = json.loads(raw[start : end + 1])
            summary = SummaryDocument.model_validate(
                {
                    "overview": str(payload.get("overview", "")).strip(),
                    "key_points": self._coerce_list(payload.get("key_points")),
                    "decisions": self._coerce_list(payload.get("decisions")),
                    "topics": self._coerce_list(payload.get("topics")),
                }
            )
            if self._summary_needs_fallback(summary):
                return self._fallback_summary(source_text)
            return summary
        except Exception:
            return self._fallback_summary(source_text)

    def _summarize_single(self, text: str, language: str = "es") -> SummaryDocument:
        raw = self._generate(self._summary_prompt(text, language), max_tokens=800, language=language)
        if raw is None:
            logger.debug("Summary fallback: LLM unavailable for chunk.")
            return self._fallback_summary(text)
        return self._summary_from_raw(raw, text)

    def _chunk_text_for_summary(self, text: str, max_chars: int) -> list[str]:
        sentences = self._split_sentences(text)
        if not sentences:
            return []
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            candidate = f"{current} {sentence}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current.strip())
                current = sentence
            else:
                current = candidate
        if current.strip():
            chunks.append(current.strip())
        return chunks

    def _token_set(self, text: str) -> set[str]:
        normalized = self._normalize_for_match(text)
        return set(re.findall(r"[a-z0-9]+", normalized))

    def _match_segment_indices(self, item_text: str, segments: list[TranscriptSegment]) -> list[int]:
        item_tokens = self._token_set(item_text)
        if not item_tokens:
            return []

        scored: list[tuple[float, int]] = []
        for idx, segment in enumerate(segments):
            seg_text = segment.text_corrected or segment.text_raw
            seg_tokens = self._token_set(seg_text)
            if not seg_tokens:
                continue
            overlap = len(item_tokens & seg_tokens) / max(len(item_tokens), 1)
            if overlap >= 0.2:
                scored.append((overlap, idx))
        if not scored:
            return []
        scored.sort(key=lambda item: item[0], reverse=True)
        return [idx for _, idx in scored[:3]]

    def _attach_citations(self, summary: SummaryDocument, segments: list[TranscriptSegment] | None) -> SummaryDocument:
        if not segments:
            return summary

        citations: list[dict[str, object]] = []
        for point in summary.key_points:
            indices = self._match_segment_indices(point, segments)
            if indices:
                citations.append(
                    {
                        "item_type": "key_point",
                        "item_text": point,
                        "segment_indices": indices,
                    }
                )
        for decision in summary.decisions:
            indices = self._match_segment_indices(decision, segments)
            if indices:
                citations.append(
                    {
                        "item_type": "decision",
                        "item_text": decision,
                        "segment_indices": indices,
                    }
                )
        summary.citations = citations or None
        return summary

    def summarize(self, text: str, segments: list[TranscriptSegment] | None = None, language: str = "es") -> SummaryDocument:
        chunk_chars = int(self.settings.services.summary_chunk_chars)
        logger.info(
            "Summary started.",
            extra={
                "ctx_text_length": len(text),
                "ctx_summary_chunk_chars": chunk_chars,
                "ctx_segments_available": bool(segments),
                "ctx_language": language,
            },
        )
        if len(text) <= chunk_chars:
            summary = self._summarize_single(text, language)
            summary = self._attach_citations(summary, segments)
            logger.info(
                "Summary completed (single pass).",
                extra={
                    "ctx_key_points": len(summary.key_points),
                    "ctx_decisions": len(summary.decisions),
                    "ctx_topics": len(summary.topics),
                    "ctx_citations": len(summary.citations or []),
                },
            )
            return summary

        chunks = self._chunk_text_for_summary(text, chunk_chars)
        if not chunks:
            summary = self._attach_citations(self._fallback_summary(text), segments)
            logger.info("Summary completed via deterministic fallback (empty chunk split).")
            return summary
        logger.info(
            "Summary using hierarchical mode.",
            extra={"ctx_chunk_count": len(chunks), "ctx_summary_chunk_chars": chunk_chars},
        )

        chunk_summaries = [self._summarize_single(chunk, language) for chunk in chunks]

        # Build a clean narrative for the merge pass — no template markers that could leak.
        merged_material_lines: list[str] = []
        for chunk_summary in chunk_summaries:
            if chunk_summary.overview:
                merged_material_lines.append(chunk_summary.overview)
            for point in chunk_summary.key_points:
                merged_material_lines.append(f"- {point}")
            for decision in chunk_summary.decisions:
                merged_material_lines.append(f"- {decision}")

        merged_material = "\n".join(merged_material_lines).strip()
        if not merged_material:
            summary = self._fallback_summary(text)
            summary = self._attach_citations(summary, segments)
            logger.info("Summary completed via deterministic fallback (no merged material).")
            return summary

        summary = self._summarize_single(merged_material, language)
        if self._summary_needs_fallback(summary):
            summary = self._fallback_summary(text)
        else:
            # Clean any residual template markers from LLM output
            summary.overview = self._strip_chunk_markers(summary.overview)
            summary.key_points = [self._strip_chunk_markers(p) for p in summary.key_points if self._strip_chunk_markers(p)]
            summary.decisions = [self._strip_chunk_markers(d) for d in summary.decisions if self._strip_chunk_markers(d)]

            merged_points: list[str] = list(summary.key_points)
            for chunk_summary in chunk_summaries:
                for item in chunk_summary.key_points:
                    cleaned = self._strip_chunk_markers(item)
                    if cleaned and cleaned not in merged_points:
                        merged_points.append(cleaned)
                    if len(merged_points) >= 7:
                        break
                if len(merged_points) >= 7:
                    break
            summary.key_points = merged_points[:7]

        summary = self._attach_citations(summary, segments)
        logger.info(
            "Summary completed (hierarchical).",
            extra={
                "ctx_key_points": len(summary.key_points),
                "ctx_decisions": len(summary.decisions),
                "ctx_topics": len(summary.topics),
                "ctx_citations": len(summary.citations or []),
            },
        )
        return summary

    def ensure_ready(self) -> None:
        try:
            self._load_llm()
        except Exception as exc:
            raise DiaricatError(
                ErrorCode.POSTPROCESS_ERROR,
                "Postprocess service could not initialize.",
                details=str(exc),
            ) from exc
