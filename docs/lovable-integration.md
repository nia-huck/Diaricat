# Integracion de UI Lovable con Diaricat v1

## Objetivo
Conectar UI externa con backend local via API HTTP, sin acoplar frontend a internals de Python.

## Flujo recomendado en UI
1. `POST /v1/projects`
2. `POST /v1/projects/{id}/run`
3. Polling de `GET /v1/jobs/{job_id}` cada 1-2 segundos
4. Al finalizar `done`, solicitar:
   - `GET /v1/projects/{id}`
   - `GET /v1/projects/{id}/transcript`
   - `GET /v1/projects/{id}/summary` (si existe)
5. Renombrado de speakers via `POST /v1/projects/{id}/speakers/rename`
6. Export final via `POST /v1/projects/{id}/export`

## Mapeo directo de estados de job a UI
- `queued`: pantalla de espera
- `running`: barra de progreso por etapa
- `done`: pantalla de resultados
- `failed`: pantalla de error con accion de reintento

## Mapeo de `stage` para feedback visual
- `validating`
- `audio`
- `transcription`
- `diarization`
- `merge`
- `correction`
- `summary`
- `done`
- `failed`
- `interrupted`

## Checklist frontend-backend
- UI usa solo rutas `/v1`
- UI no parsea logs ni archivos internos
- UI trata `error_code` como clave de UX
- UI soporta polling y reintento en fallos recuperables
- UI permite renombrar `SPEAKER_XX` y refrescar transcript
- UI usa `GET /v1/health` para verificar disponibilidad del backend
