# OpenAPI Contract v1 (frozen)

Base URL: `http://127.0.0.1:8765/v1`

## Endpoints
- `GET /health`
- `POST /projects`
- `GET /projects/{project_id}`
- `GET /projects/{project_id}/transcript`
- `GET /projects/{project_id}/summary`
- `POST /projects/{project_id}/run`
- `POST /projects/{project_id}/correct`
- `POST /projects/{project_id}/summarize`
- `POST /projects/{project_id}/speakers/rename`
- `POST /projects/{project_id}/export`
- `GET /jobs/{job_id}`
- `GET /projects/{project_id}/artifacts`

## Pipeline states
`CREATED -> VALIDATED -> AUDIO_READY -> TRANSCRIBED -> DIARIZED -> MERGED -> CORRECTED -> SUMMARIZED -> EXPORTED`

Fallback error state: `FAILED`

## Job statuses
- `queued`
- `running`
- `done`
- `failed`

## Error envelope
```json
{
  "error_code": "VALIDATION_ERROR",
  "message": "Input file not found",
  "details": "C:\\missing.mp4"
}
```
