# Documento tecnico de arquitectura y diseno de producto
## Aplicacion de escritorio Windows (v1) para transcripcion inteligente local y privada

### Capitulo 1: Arquitectura tecnica e implementacion (Codex / VS Code)

## 1. Objetivo tecnico del sistema
La solucion se disena como un pipeline local, secuencial y auditable para transformar un archivo audiovisual en un resultado util de trabajo (transcripcion con hablantes, texto corregido y resumen), manteniendo privacidad y control del usuario.

### Flujo completo y proposito por etapa
1. **Carga de archivo de video/audio**
   - Entrada unica del usuario desde UI (selector o drag and drop).
   - Objetivo: iniciar proyecto de procesamiento.
2. **Validacion del formato**
   - Verifica extension, codec y posibilidad real de decodificacion.
   - Objetivo: evitar fallos tardios y dar error temprano, claro y accionable.
3. **Extraccion de audio**
   - Si es video, se extrae pista de audio; si es audio, se toma como fuente.
   - Objetivo: unificar entrada para etapas de ASR/diarizacion.
4. **Normalizacion del audio**
   - Conversion estandar (WAV mono 16kHz) + ajuste tecnico minimo.
   - Objetivo: mejorar estabilidad y precision de modelos.
5. **Transcripcion con Whisper**
   - Genera texto por segmentos temporales.
   - Objetivo: obtener base textual robusta.
6. **Diarizacion con pyannote.audio**
   - Detecta quien habla y cuando.
   - Objetivo: separar hablantes y habilitar lectura profesional de reuniones.
7. **Fusion de speakers + texto**
   - Alinea segmentos de Whisper con tramos de diarizacion.
   - Objetivo: producir transcripcion enriquecida por turnos de habla.
8. **Correccion automatica con IA liviana local**
   - Postproceso textual conservador (no inventa contenido).
   - Objetivo: elevar legibilidad sin alterar hechos.
9. **Generacion de resumen con la misma IA**
   - Resumen general, puntos clave, decisiones y temas.
   - Objetivo: salida ejecutiva rapida para uso profesional.
10. **Renombrado manual de speakers**
    - Usuario reemplaza etiquetas tecnicas por nombres reales.
    - Objetivo: personalizacion final y claridad documental.
11. **Exportacion de resultados**
    - Guardado de transcript, resumen y metadatos.
    - Objetivo: entregar artefacto utilizable fuera de la app.

## 2. Stack tecnologico recomendado (v1)
### Stack base
- **Python**: velocidad de desarrollo y ecosistema IA maduro.
- **Whisper (implementacion local)**: ASR multilenguaje confiable.
- **pyannote.audio**: diarizacion de buena calidad para escenarios reales.
- **ffmpeg**: estandar robusto para extraccion y normalizacion de audio.
- **PySide6 (o PyQt6)**: UI desktop moderna en Windows, equilibrio entre productividad y control visual.
- **PyInstaller**: distribucion como `.exe` portable.

### Estrategia para IA liviana local (correccion + resumen)
Recomendacion pragmatica para v1:
- Disenar un servicio desacoplado de postprocesado textual con interfaz interna estable (`correct(text, context)` y `summarize(text)`).
- En fase inicial, usar un modelo local pequeno optimizado para CPU (cuantizado, contexto moderado).
- Mantener arquitectura preparada para sustituir motor (otro modelo local mas potente) sin tocar UI ni pipeline.
- Criterio principal: privacidad + baja latencia + bajo consumo de memoria.

## 3. Soporte de CPU y GPU
La aplicacion debe funcionar siempre en CPU y usar GPU solo como aceleracion opcional.

### Modos de dispositivo
- **Automatico**: detecta hardware y decide backend optimo.
- **Forzar CPU**: maxima compatibilidad/estabilidad.
- **Forzar GPU**: rendimiento cuando hay compatibilidad real.

### Impacto esperado
- **Transcripcion (Whisper)**: mayor mejora con GPU.
- **Diarizacion (pyannote)**: mejora relevante en lotes largos.
- **Modelos mas precisos/pesados**: viables con GPU y VRAM suficiente.

### Principio de diseno
- GPU es opt-in funcional, no requisito.
- Si no hay GPU compatible, UX clara: continuar en CPU sin bloquear flujo.

## 4. Arquitectura del proyecto
Estructura recomendada y rol de modulos:

```text
main.py
ui/
core/
services/
models/
utils/
exports/
assets/
temp/
config/
```

### Rol de modulos
- **main.py**: punto de entrada y bootstrap general.
- **ui/**: vistas, componentes, controladores de interaccion, estados visuales.
- **core/**: orquestacion del pipeline, estado global de proyecto, casos de uso.
- **services/**:
  - `audio_service` (ffmpeg)
  - `transcription_service` (Whisper)
  - `diarization_service` (pyannote)
  - `postprocess_service` (correccion/resumen)
  - `export_service`
- **models/**: definiciones de datos de dominio (segmento, speaker map, transcript, summary).
- **utils/**: logging, validaciones, manejo de rutas, utilitarios transversales.
- **exports/**: plantillas/salidas exportadas por defecto.
- **assets/**: iconos, estilos, recursos visuales.
- **temp/**: archivos transitorios (audio extraido, intermedios).
- **config/**: configuracion de app, preferencias de dispositivo, parametros de modelo.

## 5. Pipeline tecnico detallado
1. Usuario selecciona archivo.
2. Motor de validacion revisa formato + lectura real.
3. ffmpeg extrae audio o convierte entrada a WAV.
4. Normalizacion a mono 16kHz.
5. Whisper procesa y devuelve segmentos temporales.
6. pyannote genera segmentos de speaker.
7. Modulo de alineacion cruza ambos timelines.
8. Se construye transcript enriquecido (speaker + timestamp + texto).
9. Se envia texto al modulo de correccion conservadora.
10. El mismo modulo genera resumen estructurado.
11. Usuario renombra speakers y se recalcula vista instantaneamente.
12. Exportacion final segun formato elegido.

## 6. Modulo de correccion automatica con IA liviana
### Objetivo
Mejorar calidad textual sin reescribir contenido ni introducir inferencias.

### Funciones
- Correccion de errores frecuentes de reconocimiento.
- Puntuacion y segmentacion de frases.
- Normalizacion de numeros/expresiones.
- Limpieza de repeticiones y muletillas redundantes (conservador).

### Restricciones de seguridad semantica
- No alterar hechos.
- No agregar informacion no dicha.
- No reinterpretar intencion del hablante.
- Preservar tono factual de la conversacion.

## 7. Modulo de resumen automatico
Reutiliza el mismo motor de postprocesado textual para:
- Resumen general.
- Puntos clave.
- Decisiones/acuerdos probables.
- Temas tratados.

Debe implementarse como capacidad adicional del mismo servicio, evitando duplicacion de infraestructura y facilitando mantenimiento.

## 8. Modelo de datos interno
### Entidades conceptuales recomendadas
- **Project**: `id`, `ruta_original`, `estado_pipeline`, `dispositivo`, `timestamps_globales`.
- **TranscriptSegment**: `start`, `end`, `speaker_id`, `speaker_name`, `text_raw`, `text_corrected`.
- **SpeakerProfile**: `speaker_id` (ej. `SPEAKER_00`), `custom_name`, `color_ui`.
- **TranscriptDocument**: lista de segmentos, texto completo concatenado, metadatos de calidad.
- **SummaryDocument**: resumen general, puntos clave, decisiones, temas.

### Ejemplo conceptual
- Segmento A: `00:01:12-00:01:25`, `SPEAKER_00`, nombre `Maria`, texto original X, texto corregido Y.
- Segmento B: `00:01:25-00:01:40`, `SPEAKER_01`, nombre `Carlos`, texto original X2, texto corregido Y2.
- Resumen asociado al documento completo, no por segmento (v1).

## 9. Requisitos funcionales y no funcionales
### Funcionales
- Carga de `.mp4`, `.mp3`, `.wav`, `.mkv` (y validacion robusta).
- Pipeline completo local.
- Edicion manual de speakers.
- Correccion y resumen bajo demanda.
- Exportacion de resultados.

### No funcionales
- **Privacidad**: procesamiento local por defecto.
- **Usabilidad**: apta para usuarios no tecnicos.
- **Resiliencia**: manejo claro de errores y reintentos.
- **Observabilidad**: estados de proceso visibles.
- **Extensibilidad**: modulos desacoplados para iteraciones futuras.

## 10. Empaquetado como `.exe` portable
### Estrategia
- Empaquetar con PyInstaller en modo one-folder (recomendado v1 por tamano/control).
- Incluir binarios de ffmpeg en distribucion.
- Gestionar carpeta `temp/` limpia por proyecto/sesion.
- Tratar descarga/carga de modelos en primer uso con UX explicita.

### Consideraciones
- Ejecutable portable puede crecer significativamente por dependencias IA.
- Separar modelos del binario principal reduce friccion de actualizaciones.
- Anadir verificacion de integridad de recursos al inicio.

## 11. Riesgos y limitaciones tecnicas
- Modelos pesados incrementan tamano, RAM y tiempos de arranque.
- CPU-only puede ser lento en archivos largos.
- Superposicion de voces degrada diarizacion.
- Ruido, acentos o mala captura afectan ASR.
- Sesiones largas requieren gestion de memoria y segmentacion.
- Mapeo speaker-text puede tener incertidumbre en fronteras de segmento.

## 12. Roadmap evolutivo
- Exportacion `.docx` / `.pdf`.
- Procesamiento por lotes.
- Historial de proyectos recientes.
- Busqueda por palabra/frase en transcript.
- Navegacion por temas y timestamps.
- Correccion por fragmento o bloque seleccionado.
- Resumenes mas estructurados (acta, tareas, responsables).

## 13. Recomendacion de implementacion v1 (secuencia)
1. CLI funcional del pipeline base (sin UI).
2. Integracion estable de transcripcion + diarizacion + fusion.
3. Modulo de correccion textual conservadora.
4. Modulo de resumen reutilizando mismo servicio.
5. UI desktop (PySide6/PyQt6) con estados claros.
6. Empaquetado `.exe` portable (PyInstaller + ffmpeg + recursos).
7. Optimizacion de rendimiento, manejo de errores y UX final.
