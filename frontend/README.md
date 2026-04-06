# Diaricat Frontend (Lovable UI)

Interfaz React/Vite conectada al backend local Diaricat por HTTP (`/v1`).

## Requisitos
- Node.js 20+
- Backend Diaricat corriendo en `http://127.0.0.1:8765`

## Configuracion
1. Copiar `.env.example` a `.env`.
2. Ajustar `VITE_API_BASE_URL` si el backend corre en otro host/puerto.

```env
VITE_API_BASE_URL=http://127.0.0.1:8765/v1
```

## Desarrollo
```powershell
npm install
npm run dev
```

## Tests y build
```powershell
npm run test
npx tsc --noEmit
npm run build
```

## Flujo integrado
- `HomeScreen`: crea proyecto y lanza pipeline.
- `ProcessingScreen`: hace polling de job y muestra progreso real.
- `ResultsScreen`: muestra transcript real, renombra speakers, correccion y resumen.
- `ExportScreen`: exporta `json`, `md`, `txt` via backend.
