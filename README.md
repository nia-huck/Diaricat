<p align="center">
  <img src="frontend/src/assets/diaricat-logo.png" alt="Diaricat" width="120" />
</p>

<h1 align="center">Diaricat</h1>

<p align="center">
  <strong>Private, local-only desktop app for audio transcription with speaker diarization and AI-powered summarization.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-blueviolet" alt="Version" />
  <img src="https://img.shields.io/badge/platform-Windows-blue" alt="Platform" />
  <img src="https://img.shields.io/badge/python-3.11%2B-green" alt="Python" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
</p>

---

## What is Diaricat?

Diaricat is a Windows desktop application that transcribes audio/video files, identifies who said what (speaker diarization), and generates AI-powered summaries &mdash; **all running locally on your machine**. No data ever leaves your computer.

Diaricat is part of a broader vision for local-first AI systems focused on privacy, autonomy, and offline intelligence.

### Key Features

- **Accurate transcription** powered by [Faster Whisper](https://github.com/SYSTRAN/faster-whisper) (large-v3 model with CUDA acceleration)
- **Speaker diarization** using [SpeechBrain](https://speechbrain.github.io/) ECAPA-TDNN embeddings with custom agglomerative clustering
- **AI correction & summarization** with local LLM inference via [llama.cpp](https://github.com/ggerganov/llama.cpp) (Qwen 2.5 7B recommended)
- **100% offline & private** &mdash; no API keys, no cloud services, no data upload
- **Bilingual UI** &mdash; Spanish and English with one-click toggle
- **Multiple export formats** &mdash; TXT, SRT, DOCX, PDF, JSON
- **Modern dark UI** &mdash; glassmorphism design built with React + Tailwind CSS

---

## Design Philosophy

Diaricat follows a design language I call **Purple Space Glass**.

It blends glassmorphism, deep-space aesthetics and soft neon reflections to create interfaces that feel both modern and fluid — almost like interacting with an intelligent system rather than a static tool.

The goal is not just visual appeal, but to make AI systems feel:
- responsive
- ambient
- alive, without being intrusive

This design direction is part of a broader vision where local AI systems are not only powerful and private, but also intuitive and pleasant to use.

---

## Architecture

```
+---------------------------------------------------+
|                  Desktop Shell                     |
|              (pywebview + .NET/Edge)               |
+---------------------------------------------------+
|                  Frontend (UI)                     |
|        React  TypeScript  Vite  Tailwind           |
|           Radix UI  Lucide  shadcn/ui              |
+---------------------------------------------------+
|                 REST API Layer                     |
|           FastAPI  Uvicorn  Pydantic               |
+--------------+------------+-----------+-----------+
| Transcription|Diarization | LLM Post- |  Export   |
|   Service    |  Service   | process   |  Service  |
|  (Whisper)   |(SpeechBrain)|(llama.cpp)|(DOCX/PDF) |
+--------------+------------+-----------+-----------+
|               Pipeline Orchestrator                |
|        Job queue  Progress  Cancellation           |
+---------------------------------------------------+
```

| Component | Technology |
|-----------|-----------|
| Desktop shell | pywebview 5.x (Edge WebView2) |
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| Backend API | FastAPI + Uvicorn |
| ASR (Speech-to-Text) | Faster Whisper (CTranslate2 backend) |
| Speaker Diarization | SpeechBrain ECAPA-TDNN + custom clustering |
| LLM Inference | llama-cpp-python (GGUF models) |
| Packaging | PyInstaller (onedir mode) |

---

## Requirements

### System Requirements

| | Minimum | Recommended |
|---|---------|-------------|
| **OS** | Windows 10 64-bit | Windows 11 |
| **RAM** | 8 GB | 16 GB+ |
| **GPU** | &mdash; | NVIDIA GPU with 6+ GB VRAM |
| **Disk** | 5 GB (app + models) | 10 GB |
| **Runtime** | Edge WebView2 | Edge WebView2 |

### For Development

- Python 3.11+ (tested with 3.14)
- Node.js 18+ (for frontend)
- NVIDIA CUDA Toolkit 12.x (for GPU acceleration)
- Visual Studio Build Tools 2022 (for building llama-cpp-python)

---

## Quick Start (Pre-built)

1. Download the latest release from [Releases](../../releases)
2. Extract the `Diarcat/` folder
3. (Optional) Place a GGUF model in `workspace/models/` for AI summaries
4. Run `Diarcat.exe`

---

## Development Setup

```bash
# Clone the repository
git clone https://github.com/nia-huck/Diaricat.git
cd Diaricat

# Create Python virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install Python dependencies
pip install -e ".[dev]"

# Install torch with CUDA (optional, for GPU acceleration)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128

# Install faster-whisper and speechbrain
pip install faster-whisper speechbrain

# Install llama-cpp-python (requires Visual Studio Build Tools)
pip install llama-cpp-python

# Install frontend dependencies
cd frontend
npm install

# Start frontend dev server
npm run dev

# In another terminal, start the backend
cd ..
python -m diaricat api --host 127.0.0.1 --port 8765
```

---

## Building the Executable

```powershell
# Build the frontend
cd frontend
npm run build
cd ..

# Run PyInstaller
python -m PyInstaller packaging/diaricat.spec --distpath dist --workpath build --noconfirm

# Output: dist/Diarcat/Diarcat.exe
```

The build uses **onedir mode** for fast startup (~1 second vs minutes for onefile).

---

## LLM Models

Diaricat supports local GGUF models for transcript correction and summarization. Without a model, it falls back to rule-based processing.

### Recommended Models

| Model | Size | Min RAM | Quality |
|-------|------|---------|---------|
| Qwen 2.5 1.5B (Q4_K_M) | ~1 GB | 4 GB | Basic |
| Qwen 2.5 3B (Q4_K_M) | ~2 GB | 6 GB | Good |
| **Qwen 2.5 7B (Q4_K_M)** | ~4.7 GB | 10 GB | **Best** |

Place the `.gguf` file in `workspace/models/` and configure the path in Settings.

---

## Pipeline Stages

1. **Validation** &mdash; Verify source file exists and is a supported format
2. **Audio normalization** &mdash; Extract audio, convert to 16kHz mono WAV via FFmpeg
3. **Transcription** &mdash; Speech-to-text with Faster Whisper (chunked for long audio)
4. **Speaker diarization** &mdash; Identify speakers using ECAPA-TDNN embeddings + agglomerative clustering
5. **Segment merge** &mdash; Align ASR segments with speaker turns
6. **Correction** *(optional)* &mdash; Fix ASR errors using local LLM
7. **Summarization** *(optional)* &mdash; Generate structured summary with key points, decisions, and topics

---

## Project Structure

```
Diaricat/
├── src/diaricat/           # Python backend
│   ├── api/                # FastAPI routes and middleware
│   ├── core/               # Orchestrator, job queue, alignment
│   ├── services/           # Transcription, diarization, postprocess, export
│   ├── models/             # Pydantic domain and API models
│   ├── utils/              # Device detection, logging, compatibility
│   ├── desktop.py          # pywebview desktop shell
│   ├── main.py             # CLI entry point
│   └── settings.py         # Configuration management
├── frontend/               # React/TypeScript UI
│   └── src/
│       ├── components/     # UI components (screens, ui primitives)
│       ├── context/        # React context (AppContext, I18nContext)
│       ├── lib/            # API client, i18n translations
│       └── types/          # TypeScript type definitions
├── config/                 # Default configuration (YAML)
├── packaging/              # PyInstaller spec and runtime hooks
├── scripts/                # Build scripts
├── tests/                  # Unit tests
├── vendor/                 # Bundled FFmpeg binaries
└── pyproject.toml          # Project metadata and dependencies
```

---

## Configuration

Settings are stored in `config/default.yaml` and can be modified through the Settings screen in the app:

| Setting | Default | Description |
|---------|---------|-------------|
| `whisper_model` | `large-v3` | Whisper model size |
| `whisper_compute_type` | `float16` | Compute precision (float16/int8) |
| `diarization_profile` | `quality` | Diarization quality (fast/balanced/quality) |
| `llama_model_path` | `models/qwen2.5-7b-instruct-q4_k_m.gguf` | Path to GGUF model |
| `llama_n_ctx` | `4096` | LLM context window size |
| `device_mode` | `auto` | Device selection (auto/cpu/cuda) |

---

## Tech Stack

**Backend:** Python 3.14 &middot; FastAPI &middot; Uvicorn &middot; Pydantic &middot; PyYAML &middot; SpeechBrain &middot; Faster Whisper &middot; CTranslate2 &middot; llama-cpp-python &middot; PyInstaller

**Frontend:** React 18 &middot; TypeScript &middot; Vite &middot; Tailwind CSS &middot; Radix UI &middot; shadcn/ui &middot; Lucide Icons

**AI Models:** Whisper large-v3 (ASR) &middot; ECAPA-TDNN (speaker embeddings) &middot; Qwen 2.5 7B (correction/summary)

---

## License

MIT License — see LICENSE file for details.

---

<p align="center">
  Built with privacy in mind. Your audio never leaves your machine.
</p>
