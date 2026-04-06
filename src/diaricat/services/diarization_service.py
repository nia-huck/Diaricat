"""Local speaker diarization service (no external token required)."""

from __future__ import annotations

import logging
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from diaricat.errors import DiaricatError, ErrorCode
from diaricat.models.domain import DeviceMode, SpeakerTurn
from diaricat.settings import Settings
from diaricat.utils.speechbrain_compat import ensure_speechbrain_runtime_compat
from diaricat.utils.device import select_runtime_device

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiarizationProfile:
    window_s: float
    hop_s: float
    min_segment_s: float
    energy_quantile: float
    clustering_threshold: float
    max_speakers: int


PROFILE_CATALOG: dict[str, DiarizationProfile] = {
    # Faster, less precise boundaries.
    "fast": DiarizationProfile(
        window_s=2.0,
        hop_s=1.0,
        min_segment_s=1.0,
        energy_quantile=35.0,
        clustering_threshold=0.40,
        max_speakers=10,
    ),
    # Balanced default for most laptops.
    "balanced": DiarizationProfile(
        window_s=1.5,
        hop_s=0.75,
        min_segment_s=0.7,
        energy_quantile=28.0,
        clustering_threshold=0.37,
        max_speakers=15,
    ),
    # Higher temporal resolution with tuned clustering for ECAPA-TDNN embeddings.
    "quality": DiarizationProfile(
        window_s=1.0,
        hop_s=0.5,
        min_segment_s=0.5,
        energy_quantile=22.0,
        clustering_threshold=0.35,
        max_speakers=20,
    ),
}


class PyannoteDiarizationService:
    """Backwards-compatible name, now implemented with a fully local pipeline."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._embedders: dict[str, object] = {}
        self._embedder_lock = threading.Lock()
        self._last_metadata: dict[str, object] = {
            "backend_used": "spectral",
            "fallback_reason": None,
            "diarization_degraded": False,
        }
        self._ensure_hf_token()

    def _ensure_hf_token(self) -> None:
        """Inject HuggingFace token from settings into environment for SpeechBrain model downloads."""
        import os
        token = (self.settings.services.hf_token or "").strip()
        env_key = (self.settings.services.hf_token_env or "HUGGINGFACE_TOKEN").strip()
        if token:
            os.environ.setdefault(env_key, token)
            os.environ.setdefault("HF_TOKEN", token)
            os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", token)
            logger.info("HuggingFace token injected into environment from settings.")
        else:
            # SpeechBrain ECAPA model is public — no token needed for download.
            # Set a flag so we know token was absent (for diagnostics).
            logger.debug("No HuggingFace token configured — using public model access.")

    def get_last_metadata(self) -> dict[str, object]:
        return dict(self._last_metadata)

    @staticmethod
    def _audio_duration_seconds(audio_path: Path) -> float:
        try:
            with wave.open(str(audio_path), "rb") as wav:
                frames = wav.getnframes()
                framerate = wav.getframerate()
            if framerate <= 0:
                return 0.0
            return float(frames) / float(framerate)
        except Exception:
            return 0.0

    def _fallback_single_speaker(self, audio_path: Path, reason: str) -> list[SpeakerTurn]:
        duration = max(self._audio_duration_seconds(audio_path), 0.1)
        self._last_metadata = {
            "backend_used": "fallback_single_speaker",
            "fallback_reason": reason,
            "diarization_degraded": True,
        }
        logger.warning(
            "Local diarization fallback to single speaker.",
            extra={"extra": {"reason": reason, "duration_seconds": duration}},
        )
        return [SpeakerTurn(start=0.0, end=duration, speaker_id="SPEAKER_00")]

    def _get_profile(self) -> DiarizationProfile:
        requested = (self.settings.services.diarization_profile or "balanced").strip().lower()
        return PROFILE_CATALOG.get(requested, PROFILE_CATALOG["balanced"])

    def _get_embedder(self, device: str = "cpu") -> object:
        requested_device = "cuda" if str(device).lower().startswith("cuda") else "cpu"
        with self._embedder_lock:
            cached = self._embedders.get(requested_device)
            if cached is not None:
                return cached

            ensure_speechbrain_runtime_compat()

            model_dir = self.settings.app.workspace_dir / "models" / "diarization" / "ecapa"
            model_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                "Loading SpeechBrain ECAPA embedder.",
                extra={
                    "ctx_device": requested_device,
                    "ctx_model_dir": str(model_dir),
                    "ctx_model_dir_exists": model_dir.exists(),
                    "ctx_model_files": [f.name for f in model_dir.iterdir()] if model_dir.exists() else [],
                },
            )

            try:
                from speechbrain.inference.speaker import EncoderClassifier  # type: ignore
            except ImportError as exc:
                logger.error("SpeechBrain not installed: %s", exc)
                raise

            # Try loading with LocalStrategy first (offline-friendly)
            try:
                from speechbrain.utils.fetching import LocalStrategy  # type: ignore
                embedder = EncoderClassifier.from_hparams(
                    source="speechbrain/spkrec-ecapa-voxceleb",
                    savedir=str(model_dir),
                    run_opts={"device": requested_device},
                    local_strategy=LocalStrategy.COPY,
                )
            except Exception as local_exc:
                logger.warning(
                    "SpeechBrain ECAPA load with LocalStrategy failed, retrying without: %s",
                    local_exc,
                )
                # Fallback: let SpeechBrain download the model normally
                embedder = EncoderClassifier.from_hparams(
                    source="speechbrain/spkrec-ecapa-voxceleb",
                    savedir=str(model_dir),
                    run_opts={"device": requested_device},
                )

            self._embedders[requested_device] = embedder
            logger.info("SpeechBrain ECAPA embedder loaded successfully on %s.", requested_device)
            return embedder

    @staticmethod
    def _resample_linear(signal: np.ndarray, source_sr: int, target_sr: int) -> np.ndarray:
        if source_sr == target_sr:
            return signal.astype(np.float32)
        if signal.size == 0 or source_sr <= 0 or target_sr <= 0:
            return np.zeros((0,), dtype=np.float32)

        duration = signal.size / float(source_sr)
        target_len = max(int(round(duration * target_sr)), 1)
        src_pos = np.linspace(0.0, 1.0, num=signal.size, endpoint=False, dtype=np.float64)
        dst_pos = np.linspace(0.0, 1.0, num=target_len, endpoint=False, dtype=np.float64)
        return np.interp(dst_pos, src_pos, signal).astype(np.float32)

    def _load_audio(self, audio_path: Path) -> tuple[np.ndarray, int]:
        target_sr = 16000

        # First path: read normalized PCM WAV directly (fast and dependency-free).
        try:
            with wave.open(str(audio_path), "rb") as wav:
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                sample_rate = wav.getframerate()
                frame_count = wav.getnframes()
                raw = wav.readframes(frame_count)
        except Exception:
            raw = b""
            channels = 0
            sample_width = 0
            sample_rate = 0

        if raw and channels > 0 and sample_width > 0 and sample_rate > 0:
            if sample_width == 1:
                data = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
                data = (data - 128.0) / 128.0
            elif sample_width == 2:
                data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            elif sample_width == 4:
                data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                data = np.zeros((0,), dtype=np.float32)

            if channels > 1 and data.size >= channels:
                usable = (data.size // channels) * channels
                data = data[:usable].reshape(-1, channels).mean(axis=1)
            if sample_rate != target_sr:
                data = self._resample_linear(data, sample_rate, target_sr)

            data = np.clip(data, -1.0, 1.0).astype(np.float32)
            if data.size > 0:
                return data, target_sr

        # Fallback: torchaudio for uncommon WAV encodings.
        try:
            import torchaudio  # type: ignore
        except Exception as exc:
            raise DiaricatError(
                ErrorCode.DIARIZATION_ERROR,
                "Failed to decode audio for diarization.",
                details=f"WAV decode failed and torchaudio unavailable: {exc}",
            ) from exc

        try:
            waveform, sr = torchaudio.load(str(audio_path))
            if waveform.ndim > 1:
                waveform = waveform.mean(dim=0, keepdim=True)
            if sr != target_sr:
                waveform = torchaudio.functional.resample(waveform, sr, target_sr)
                sr = target_sr
            mono = waveform.squeeze(0).detach().cpu().numpy().astype(np.float32)
            if mono.size == 0:
                raise ValueError("Empty audio waveform")
            mono = np.clip(mono, -1.0, 1.0)
            return mono, int(sr)
        except Exception as exc:
            raise DiaricatError(
                ErrorCode.DIARIZATION_ERROR,
                "Failed to decode audio for diarization.",
                details=str(exc),
            ) from exc

    @staticmethod
    def _window_rms(signal: np.ndarray) -> float:
        if signal.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(signal), dtype=np.float64)))

    def _collect_voiced_windows(
        self,
        signal: np.ndarray,
        sample_rate: int,
        profile: DiarizationProfile,
    ) -> list[tuple[float, float]]:
        duration_s = signal.size / float(sample_rate)
        win = max(int(profile.window_s * sample_rate), 1)
        hop = max(int(profile.hop_s * sample_rate), 1)

        candidates: list[tuple[float, float, float]] = []
        for start in range(0, max(signal.size - win + 1, 1), hop):
            end = min(start + win, signal.size)
            chunk = signal[start:end]
            if chunk.size < int(0.3 * win):
                continue
            rms = self._window_rms(chunk)
            candidates.append((start / sample_rate, end / sample_rate, rms))

        if not candidates:
            return [(0.0, max(duration_s, 0.1))]

        energy_values = np.array([c[2] for c in candidates], dtype=np.float32)
        safe_energy = np.maximum(energy_values, 1e-8)
        log_energy = np.log1p(safe_energy * 1000.0)

        # Hybrid threshold in log-energy space to avoid discarding quiet speakers.
        quantile_threshold = float(np.quantile(log_energy, profile.energy_quantile / 100.0))
        q25, q75 = np.quantile(log_energy, [0.25, 0.75])
        iqr = float(max(q75 - q25, 1e-6))
        median_energy = float(np.median(log_energy))
        spread_floor = float(np.min(log_energy) + 0.08 * (np.max(log_energy) - np.min(log_energy)))
        adaptive_floor = max(median_energy - 1.1 * iqr, spread_floor)
        threshold = max(quantile_threshold, adaptive_floor)

        voiced_mask = log_energy >= threshold
        if np.any(voiced_mask):
            # Expand one hop on each side to preserve low-energy speech edges.
            expanded = voiced_mask.copy()
            expanded[1:] = expanded[1:] | voiced_mask[:-1]
            expanded[:-1] = expanded[:-1] | voiced_mask[1:]
            voiced_mask = expanded

        min_keep = max(3, int(round(len(candidates) * 0.30)))
        if int(np.sum(voiced_mask)) < min_keep:
            top_indices = np.argsort(log_energy)[-min_keep:]
            voiced_mask[top_indices] = True

        voiced_indices = np.flatnonzero(voiced_mask)
        voiced = [(candidates[i][0], candidates[i][1]) for i in voiced_indices]
        return voiced

    @staticmethod
    def _extract_window_feature(chunk: np.ndarray, sample_rate: int) -> np.ndarray | None:
        if chunk.size < int(0.2 * sample_rate):
            return None

        chunk = chunk.astype(np.float32)
        chunk = chunk - float(np.mean(chunk))
        rms = float(np.sqrt(np.mean(np.square(chunk), dtype=np.float64)))
        if rms <= 1e-6:
            return None

        n_fft = int(2 ** np.ceil(np.log2(max(chunk.size, 256))))
        window = np.hanning(chunk.size).astype(np.float32)
        padded = np.zeros((n_fft,), dtype=np.float32)
        padded[: chunk.size] = chunk * window

        spectrum = np.abs(np.fft.rfft(padded)).astype(np.float32) + 1e-8
        power = spectrum * spectrum
        freqs = np.fft.rfftfreq(n_fft, d=1.0 / float(sample_rate)).astype(np.float32)
        total_power = float(np.sum(power)) + 1e-9

        centroid_hz = float(np.sum(freqs * power) / total_power)
        spread_hz = float(np.sqrt(np.sum(np.square(freqs - centroid_hz) * power) / total_power))
        cumulative = np.cumsum(power)
        rolloff_idx = int(np.searchsorted(cumulative, 0.85 * total_power))
        rolloff_hz = float(freqs[min(rolloff_idx, freqs.size - 1)])

        signs = np.signbit(chunk).astype(np.int8)
        zcr = float(np.mean(np.abs(np.diff(signs))))

        band_edges = [80.0, 250.0, 500.0, 1000.0, 1800.0, 2800.0, 4000.0, 6000.0]
        band_features: list[float] = []
        for low, high in zip(band_edges[:-1], band_edges[1:], strict=False):
            mask = (freqs >= low) & (freqs < high)
            band_power = float(np.sum(power[mask])) if np.any(mask) else 0.0
            band_features.append(np.log1p(band_power))

        return np.array(
            [
                np.log1p(rms * 1000.0),
                zcr,
                centroid_hz / 4000.0,
                spread_hz / 4000.0,
                rolloff_hz / 4000.0,
                *band_features,
            ],
            dtype=np.float32,
        )

    @staticmethod
    def _normalize_features(features: np.ndarray) -> np.ndarray:
        mean = features.mean(axis=0, keepdims=True)
        std = features.std(axis=0, keepdims=True)
        std = np.where(std < 1e-6, 1.0, std)
        return (features - mean) / std

    def _extract_features(
        self,
        signal: np.ndarray,
        sample_rate: int,
        windows: list[tuple[float, float]],
    ) -> tuple[np.ndarray, list[tuple[float, float]]]:
        vectors: list[np.ndarray] = []
        valid_windows: list[tuple[float, float]] = []

        for start_s, end_s in windows:
            start = max(int(start_s * sample_rate), 0)
            end = min(int(end_s * sample_rate), signal.size)
            chunk = signal[start:end]
            feature = self._extract_window_feature(chunk, sample_rate)
            if feature is None:
                continue
            vectors.append(feature)
            valid_windows.append((start_s, end_s))

        if not vectors:
            return np.zeros((0, 0), dtype=np.float32), []

        features = np.stack(vectors, axis=0)
        return self._normalize_features(features), valid_windows

    def _extract_speechbrain_embeddings(
        self,
        signal: np.ndarray,
        sample_rate: int,
        windows: list[tuple[float, float]],
        device: str = "cpu",
    ) -> tuple[np.ndarray, list[tuple[float, float]]]:
        try:
            import torch  # type: ignore
        except Exception:
            return np.zeros((0, 0), dtype=np.float32), []

        try:
            embedder = self._get_embedder(device=device)
            runtime_device = "cuda" if str(device).lower().startswith("cuda") else "cpu"
        except Exception as exc:
            if str(device).lower().startswith("cuda"):
                logger.warning(
                    "SpeechBrain CUDA embedder unavailable, retrying on CPU: %s (type=%s)",
                    exc, type(exc).__name__,
                )
                try:
                    embedder = self._get_embedder(device="cpu")
                    runtime_device = "cpu"
                except Exception as cpu_exc:
                    logger.error(
                        "SpeechBrain embedder unavailable on both CUDA and CPU, using spectral fallback: %s (type=%s)",
                        cpu_exc, type(cpu_exc).__name__,
                    )
                    return np.zeros((0, 0), dtype=np.float32), []
            else:
                logger.error(
                    "SpeechBrain embedder unavailable, using spectral fallback: %s (type=%s)",
                    exc, type(exc).__name__,
                )
                return np.zeros((0, 0), dtype=np.float32), []

        vectors: list[np.ndarray] = []
        valid_windows: list[tuple[float, float]] = []
        for start_s, end_s in windows:
            start = max(int(start_s * sample_rate), 0)
            end = min(int(end_s * sample_rate), signal.size)
            chunk = signal[start:end]
            if chunk.size < int(0.2 * sample_rate):
                continue

            try:
                wav = torch.from_numpy(chunk.astype(np.float32)).unsqueeze(0)
                if runtime_device != "cpu":
                    wav = wav.to(runtime_device)
                with torch.inference_mode():
                    embedding = embedder.encode_batch(wav)
            except Exception:
                continue

            vector = embedding.squeeze().detach().cpu().numpy().astype(np.float32)
            if vector.ndim != 1:
                vector = vector.reshape(-1)
            if vector.size == 0:
                continue
            # L2-normalize embeddings for cosine similarity clustering
            norm = float(np.linalg.norm(vector))
            if norm > 1e-6:
                vector = vector / norm
            vectors.append(vector)
            valid_windows.append((start_s, end_s))

        if not vectors:
            return np.zeros((0, 0), dtype=np.float32), []

        features = np.stack(vectors, axis=0)
        return features, valid_windows

    @staticmethod
    def _l2_normalize_rows(values: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        norms = np.where(norms < 1e-8, 1.0, norms)
        return values / norms

    @staticmethod
    def _cosine_distance_matrix(features: np.ndarray) -> np.ndarray:
        """Compute pairwise cosine distance matrix (1 - cosine_similarity)."""
        normalized = PyannoteDiarizationService._l2_normalize_rows(features)
        similarity = np.clip(normalized @ normalized.T, -1.0, 1.0)
        return 1.0 - similarity

    @staticmethod
    def _agglomerative_cluster(
        dist_matrix: np.ndarray,
        threshold: float,
        max_clusters: int,
    ) -> np.ndarray:
        """Simple agglomerative clustering with average linkage and cosine distance."""
        n = dist_matrix.shape[0]
        if n <= 1:
            return np.zeros((n,), dtype=np.int32)

        # Each sample starts as its own cluster
        clusters: dict[int, list[int]] = {i: [i] for i in range(n)}
        next_id = n

        while len(clusters) > 1:
            # Find minimum average-linkage distance between any two clusters
            active = sorted(clusters.keys())
            if len(active) <= 1:
                break

            best_dist = float("inf")
            best_pair = (active[0], active[1])

            for i_idx in range(len(active)):
                for j_idx in range(i_idx + 1, len(active)):
                    ci, cj = active[i_idx], active[j_idx]
                    members_i = clusters[ci]
                    members_j = clusters[cj]
                    # Average linkage: mean distance between all pairs
                    total = 0.0
                    count = 0
                    for mi in members_i:
                        for mj in members_j:
                            total += dist_matrix[mi, mj]
                            count += 1
                    avg_dist = total / max(count, 1)
                    if avg_dist < best_dist:
                        best_dist = avg_dist
                        best_pair = (ci, cj)

            # Use a softer limit while cluster count is still above the target.
            merge_limit = threshold if len(clusters) <= max_clusters else min(threshold * 1.35, 0.95)
            if best_dist > merge_limit:
                break

            # Merge the two closest clusters
            ci, cj = best_pair
            merged = clusters[ci] + clusters[cj]
            del clusters[ci]
            del clusters[cj]
            clusters[next_id] = merged
            next_id += 1

            if len(clusters) <= 1:
                break

        # Assign labels
        labels = np.zeros((n,), dtype=np.int32)
        for label_id, (_, members) in enumerate(sorted(clusters.items())):
            for member in members:
                labels[member] = label_id

        return labels

    @staticmethod
    def _silhouette_score_cosine(
        dist_matrix: np.ndarray, labels: np.ndarray, max_samples: int = 256,
    ) -> float:
        """Approximate silhouette score from a bounded sample of rows."""
        n_samples = labels.size
        if n_samples < 3:
            return -1.0

        unique = np.unique(labels)
        if unique.size < 2:
            return -1.0

        if n_samples <= max_samples:
            eval_indices = np.arange(n_samples, dtype=np.int32)
        else:
            rng = np.random.default_rng(0)
            mandatory = [int(np.flatnonzero(labels == label)[0]) for label in unique]
            if len(mandatory) >= max_samples:
                eval_indices = np.array(mandatory[:max_samples], dtype=np.int32)
            else:
                selected = np.zeros((n_samples,), dtype=bool)
                selected[mandatory] = True
                remaining = np.flatnonzero(~selected)
                budget = max_samples - len(mandatory)
                if remaining.size > budget:
                    extra = rng.choice(remaining, size=budget, replace=False)
                else:
                    extra = remaining
                eval_indices = np.array(mandatory + extra.tolist(), dtype=np.int32)

        scores = np.zeros(eval_indices.size, dtype=np.float64)
        valid = np.zeros(eval_indices.size, dtype=bool)

        for out_idx, idx in enumerate(eval_indices):
            own = labels[idx]
            same_mask = labels == own
            same_count = int(np.sum(same_mask)) - 1  # exclude self
            if same_count <= 0:
                continue

            same_mask_no_self = same_mask.copy()
            same_mask_no_self[idx] = False
            a = float(np.mean(dist_matrix[idx, same_mask_no_self]))

            b = float("inf")
            for other in unique:
                if other == own:
                    continue
                other_mask = labels == other
                if not np.any(other_mask):
                    continue
                b = min(b, float(np.mean(dist_matrix[idx, other_mask])))

            if not np.isfinite(b):
                continue
            denom = max(a, b, 1e-6)
            scores[out_idx] = (b - a) / denom
            valid[out_idx] = True

        if not np.any(valid):
            return -1.0
        return float(np.mean(scores[valid]))

    @staticmethod
    def _smooth_labels(labels: np.ndarray, radius: int = 1) -> np.ndarray:
        if labels.size < 3:
            return labels
        smoothed = labels.copy()
        for idx in range(labels.size):
            start = max(0, idx - radius)
            end = min(labels.size, idx + radius + 1)
            window = labels[start:end]
            values, counts = np.unique(window, return_counts=True)
            smoothed[idx] = values[int(np.argmax(counts))]
        return smoothed

    @staticmethod
    def _absorb_short_segments(
        segments: list[tuple[float, float, int]],
        min_duration_s: float,
    ) -> list[tuple[float, float, int]]:
        """Absorb isolated short speaker segments into the dominant neighbor."""
        if len(segments) < 3:
            return segments
        changed = True
        while changed:
            changed = False
            result: list[tuple[float, float, int]] = []
            for i, (s, e, lbl) in enumerate(segments):
                dur = e - s
                if dur >= min_duration_s or len(segments) <= 1:
                    result.append((s, e, lbl))
                    continue
                # Absorb into the longer neighbor
                prev_lbl = result[-1][2] if result else None
                next_lbl = segments[i + 1][2] if i + 1 < len(segments) else None
                if prev_lbl is not None and prev_lbl == next_lbl:
                    # Both neighbors are the same speaker -> extend previous
                    result[-1] = (result[-1][0], e, prev_lbl)
                    changed = True
                elif prev_lbl is not None:
                    result[-1] = (result[-1][0], e, prev_lbl)
                    changed = True
                elif next_lbl is not None:
                    segments[i + 1] = (s, segments[i + 1][1], next_lbl)
                    changed = True
                else:
                    result.append((s, e, lbl))
            segments = result
        return segments

    def _reassign_small_clusters(
        self,
        labels: np.ndarray,
        features: np.ndarray,
        min_cluster_size: int,
    ) -> np.ndarray:
        if labels.size == 0:
            return labels

        working = labels.astype(np.int32).copy()
        target_min = max(int(min_cluster_size), 1)
        normalized = self._l2_normalize_rows(features.astype(np.float32, copy=False))

        while True:
            unique, counts = np.unique(working, return_counts=True)
            if unique.size < 2:
                break

            small_labels = [int(label) for label, count in zip(unique, counts, strict=False) if int(count) < target_min]
            if not small_labels:
                break

            large_labels = [int(label) for label, count in zip(unique, counts, strict=False) if int(count) >= target_min]
            if not large_labels:
                break

            large_centroids = np.stack([normalized[working == label].mean(axis=0) for label in large_labels], axis=0)
            large_centroids = self._l2_normalize_rows(large_centroids)
            large_label_ids = np.array(large_labels, dtype=np.int32)
            changed = False

            for small_label in small_labels:
                idx = np.where(working == small_label)[0]
                if idx.size == 0:
                    continue
                distances = 1.0 - np.clip(normalized[idx] @ large_centroids.T, -1.0, 1.0)
                nearest = large_label_ids[np.argmin(distances, axis=1)]
                working[idx] = nearest
                changed = True

            if not changed:
                break

        unique_sorted = sorted(np.unique(working).tolist())
        remap = {int(label): idx for idx, label in enumerate(unique_sorted)}
        return np.array([remap[int(label)] for label in working], dtype=np.int32)

    _MAX_CLUSTER_SAMPLES = 300  # subsample above this to keep clustering fast

    @staticmethod
    def _subsample_indices(n_samples: int, max_samples: int) -> np.ndarray:
        """Return evenly-spaced indices so temporal coverage is preserved."""
        if n_samples <= max_samples:
            return np.arange(n_samples, dtype=np.int32)
        return np.linspace(0, n_samples - 1, num=max_samples, dtype=np.int32)

    def _propagate_labels(
        self, features: np.ndarray, core_indices: np.ndarray, core_labels: np.ndarray,
    ) -> np.ndarray:
        """Assign every sample to the nearest core-cluster centroid (cosine)."""
        unique_labels = np.unique(core_labels)
        centroids = np.stack(
            [features[core_indices[core_labels == lbl]].mean(axis=0) for lbl in unique_labels],
            axis=0,
        )
        centroids = self._l2_normalize_rows(centroids)
        all_norm = self._l2_normalize_rows(features)
        # cosine distance: 1 - dot
        distances = 1.0 - np.clip(all_norm @ centroids.T, -1.0, 1.0)
        return unique_labels[np.argmin(distances, axis=1)].astype(np.int32)

    def _cluster_features(self, features: np.ndarray, profile: DiarizationProfile) -> np.ndarray:
        n_samples = features.shape[0]
        if n_samples <= 1:
            return np.zeros((n_samples,), dtype=np.int32)

        max_k = min(profile.max_speakers, max(2, n_samples // 2))
        if max_k <= 1:
            return np.zeros((n_samples,), dtype=np.int32)

        # Subsample for clustering if too many windows (keeps O(n³) tractable)
        core_idx = self._subsample_indices(n_samples, self._MAX_CLUSTER_SAMPLES)
        core_features = features[core_idx]
        n_core = core_features.shape[0]

        min_cluster_size = max(2, int(round(n_core * 0.02)))

        # Compute cosine distance matrix on the (smaller) core set
        dist_matrix = self._cosine_distance_matrix(core_features)
        cluster_threshold = self._effective_clustering_threshold(profile.clustering_threshold, n_core)

        # Primary: agglomerative clustering with cosine distance
        core_labels = self._agglomerative_cluster(
            dist_matrix, threshold=cluster_threshold, max_clusters=max_k,
        )
        core_labels = self._reassign_small_clusters(core_labels, core_features, min_cluster_size)

        n_clusters = len(np.unique(core_labels))
        if n_clusters < 2:
            # Fallback: try with a more permissive threshold
            fallback_threshold = min(cluster_threshold * 1.2, 0.95)
            core_labels = self._agglomerative_cluster(
                dist_matrix, threshold=fallback_threshold, max_clusters=max_k,
            )
            core_labels = self._reassign_small_clusters(core_labels, core_features, min_cluster_size)
            if len(np.unique(core_labels)) < 2:
                return np.zeros((n_samples,), dtype=np.int32)

        # Validate with silhouette score
        score = self._silhouette_score_cosine(dist_matrix, core_labels)
        if score < 0.05:
            # Very poor clustering - try forcing 2 speakers
            forced = self._agglomerative_cluster(
                dist_matrix, threshold=1.0, max_clusters=2,
            )
            forced = self._reassign_small_clusters(forced, core_features, min_cluster_size)
            if len(np.unique(forced)) >= 2:
                forced_score = self._silhouette_score_cosine(dist_matrix, forced)
                if forced_score > score:
                    core_labels = forced
                    score = forced_score
            if score < 0.02:
                return np.zeros((n_samples,), dtype=np.int32)

        # Propagate labels to all samples (if we subsampled)
        if n_core < n_samples:
            labels = self._propagate_labels(features, core_idx, core_labels)
        else:
            labels = core_labels

        return self._smooth_labels(labels.astype(np.int32), radius=4)

    @staticmethod
    def _effective_clustering_threshold(base_threshold: float, n_samples: int) -> float:
        if n_samples <= 8:
            scale = 1.35
        elif n_samples <= 20:
            scale = 1.2
        elif n_samples <= 60:
            scale = 1.1
        else:
            scale = 1.0
        return float(min(max(base_threshold * scale, 0.05), 0.95))

    @staticmethod
    def _merge_labeled_windows(
        windows: list[tuple[float, float]],
        labels: np.ndarray,
        min_segment_s: float,
    ) -> list[tuple[float, float, int]]:
        merged: list[tuple[float, float, int]] = []
        for (start, end), label in zip(windows, labels, strict=False):
            if not merged:
                merged.append((start, end, int(label)))
                continue
            prev_s, prev_e, prev_label = merged[-1]
            if prev_label == int(label) and start <= prev_e + 0.15:
                merged[-1] = (prev_s, max(prev_e, end), prev_label)
            else:
                merged.append((start, end, int(label)))

        compact: list[tuple[float, float, int]] = []
        for idx, segment in enumerate(merged):
            start, end, label = segment
            if (end - start) >= min_segment_s or len(merged) == 1:
                compact.append(segment)
                continue

            if idx > 0:
                prev_s, _, prev_label = compact[-1]
                compact[-1] = (prev_s, end, prev_label)
            elif idx + 1 < len(merged):
                next_start, next_end, next_label = merged[idx + 1]
                merged[idx + 1] = (start, next_end, next_label)
            else:
                compact.append(segment)
        return compact

    @staticmethod
    def _to_speaker_turns(segments: list[tuple[float, float, int]]) -> list[SpeakerTurn]:
        label_map: dict[int, str] = {}
        turns: list[SpeakerTurn] = []
        next_id = 0
        for start, end, label in segments:
            if label not in label_map:
                label_map[label] = f"SPEAKER_{next_id:02d}"
                next_id += 1
            turns.append(
                SpeakerTurn(
                    start=float(max(start, 0.0)),
                    end=float(max(end, start + 0.05)),
                    speaker_id=label_map[label],
                )
            )
        return turns

    def diarize(self, audio_path: Path, device_mode: DeviceMode) -> list[SpeakerTurn]:
        import time as _time
        runtime_device = select_runtime_device(device_mode)

        profile = self._get_profile()
        backend_used = "speechbrain"
        logger.info(
            "Diarization started.",
            extra={
                "ctx_audio_path": str(audio_path),
                "ctx_profile": self.settings.services.diarization_profile,
                "ctx_window_s": profile.window_s,
                "ctx_hop_s": profile.hop_s,
                "ctx_clustering_threshold": profile.clustering_threshold,
                "ctx_max_speakers": profile.max_speakers,
                "ctx_device": runtime_device,
            },
        )
        try:
            t0 = _time.monotonic()
            signal, sample_rate = self._load_audio(audio_path)
            audio_duration_s = round(signal.size / float(sample_rate), 2)
            logger.info(
                "Diarization audio loaded.",
                extra={
                    "ctx_audio_duration_s": audio_duration_s,
                    "ctx_sample_rate": sample_rate,
                    "ctx_signal_samples": signal.size,
                    "ctx_load_ms": int((_time.monotonic() - t0) * 1000),
                },
            )

            t1 = _time.monotonic()
            windows = self._collect_voiced_windows(signal, sample_rate, profile)
            logger.info(
                "Diarization voiced windows collected.",
                extra={
                    "ctx_window_count": len(windows),
                    "ctx_collect_ms": int((_time.monotonic() - t1) * 1000),
                },
            )

            t2 = _time.monotonic()
            features, valid_windows = self._extract_speechbrain_embeddings(
                signal, sample_rate, windows, device=runtime_device,
            )
            sb_ms = int((_time.monotonic() - t2) * 1000)
            if features.shape[0] == 0:
                logger.warning(
                    "SpeechBrain embeddings returned 0 vectors (took %dms). Falling back to spectral features.",
                    sb_ms,
                )
                backend_used = "spectral"
                t3 = _time.monotonic()
                features, valid_windows = self._extract_features(signal, sample_rate, windows)
                logger.info(
                    "Spectral features extracted.",
                    extra={
                        "ctx_spectral_feature_count": int(features.shape[0]),
                        "ctx_spectral_ms": int((_time.monotonic() - t3) * 1000),
                    },
                )
            else:
                logger.info(
                    "SpeechBrain embeddings extracted.",
                    extra={
                        "ctx_embedding_count": int(features.shape[0]),
                        "ctx_embedding_dim": int(features.shape[1]) if features.ndim == 2 else 0,
                        "ctx_speechbrain_ms": sb_ms,
                    },
                )

            if features.shape[0] == 0:
                return self._fallback_single_speaker(audio_path, "No voiced windows with valid features.")

            logger.info(
                "Diarization features prepared.",
                extra={
                    "ctx_backend_used": backend_used,
                    "ctx_window_count": len(windows),
                    "ctx_valid_window_count": len(valid_windows),
                    "ctx_feature_count": int(features.shape[0]),
                    "ctx_feature_dim": int(features.shape[1]) if features.ndim == 2 else 0,
                },
            )

            t4 = _time.monotonic()
            labels = self._cluster_features(features, profile)
            n_clusters = len(np.unique(labels))
            logger.info(
                "Diarization clustering completed.",
                extra={
                    "ctx_cluster_count": n_clusters,
                    "ctx_label_distribution": {str(l): int(c) for l, c in zip(*np.unique(labels, return_counts=True))},
                    "ctx_clustering_ms": int((_time.monotonic() - t4) * 1000),
                },
            )

            merged = self._merge_labeled_windows(valid_windows, labels, profile.min_segment_s)
            # Absorb brief isolated speaker flickers into surrounding turns
            min_turn_s = max(profile.min_segment_s * 2.0, 1.5)
            merged = self._absorb_short_segments(merged, min_turn_s)
            turns = self._to_speaker_turns(merged)
            if not turns:
                return self._fallback_single_speaker(audio_path, "Clustering produced no turns.")
            unique_speakers = len(set(t.speaker_id for t in turns))
            total_ms = int((_time.monotonic() - t0) * 1000)
            self._last_metadata = {
                "backend_used": backend_used,
                "fallback_reason": None,
                "diarization_degraded": backend_used != "speechbrain",
                "speaker_turn_count": len(turns),
                "unique_speaker_count": unique_speakers,
                "audio_duration_s": audio_duration_s,
            }
            logger.info(
                "Diarization completed successfully.",
                extra={
                    "ctx_backend_used": backend_used,
                    "ctx_diarization_degraded": backend_used != "speechbrain",
                    "ctx_speaker_turn_count": len(turns),
                    "ctx_unique_speakers": unique_speakers,
                    "ctx_audio_duration_s": audio_duration_s,
                    "ctx_total_diarization_ms": total_ms,
                },
            )
            return turns
        except DiaricatError as exc:
            logger.warning(
                "Diarization encountered error, falling back to single speaker.",
                extra={
                    "ctx_error_code": str(exc.code),
                    "ctx_error_message": exc.message,
                    "ctx_error_details": exc.details,
                    "ctx_failure_component": exc.failure_component,
                },
            )
            return self._fallback_single_speaker(audio_path, exc.message)
        except Exception as exc:
            logger.error("Diarization unexpected error: %s (type=%s)", exc, type(exc).__name__)
            raise DiaricatError(
                ErrorCode.DIARIZATION_ERROR,
                "Local diarization failed.",
                details=str(exc),
            ) from exc
