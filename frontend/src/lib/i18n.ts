const LANG_KEY = 'diaricat.language';

export type Lang = 'es' | 'en';

export const getStoredLang = (): Lang => {
  try {
    const v = localStorage.getItem(LANG_KEY);
    if (v === 'en' || v === 'es') return v;
  } catch { /* ignore */ }
  return 'es';
};

export const storeLang = (lang: Lang) => {
  try { localStorage.setItem(LANG_KEY, lang); } catch { /* ignore */ }
};

type Translations = Record<string, Record<Lang, string>>;

const t: Translations = {
  // ── Screens ──
  'screen.home': { es: 'Inicio', en: 'Home' },
  'screen.processing': { es: 'Procesando', en: 'Processing' },
  'screen.results': { es: 'Resultados', en: 'Results' },
  'screen.export': { es: 'Exportar', en: 'Export' },
  'screen.settings': { es: 'Configuracion', en: 'Settings' },
  'screen.setup': { es: 'Configuracion inicial', en: 'Initial setup' },

  // ── HomeScreen ──
  'home.dropzone': { es: 'Arrastra el archivo aqui o', en: 'Drag the file here or' },
  'home.select': { es: 'seleccionalo', en: 'select it' },
  'home.uploading': { es: 'Transfiriendo al backend local...', en: 'Transferring to local backend...' },
  'home.unsupported': { es: 'Formato no soportado. Usa:', en: 'Unsupported format. Use:' },
  'home.start': { es: 'Iniciar', en: 'Start' },
  'home.compute': { es: 'Modo de computo', en: 'Compute mode' },
  'home.recent': { es: 'Recientes', en: 'Recent' },
  'home.noRecent': { es: 'Sin ejecuciones recientes.', en: 'No recent runs.' },
  'home.reuse': { es: 'Reusar', en: 'Reuse' },
  'home.pathPlaceholder': { es: 'C:\\Users\\...\\reunion.mp4', en: 'C:\\Users\\...\\meeting.mp4' },

  // ── ProcessingScreen ──
  'stage.queued': { es: 'En cola', en: 'Queued' },
  'stage.running': { es: 'Ejecutando pipeline', en: 'Running pipeline' },
  'stage.validating': { es: 'Validando archivo', en: 'Validating file' },
  'stage.audio': { es: 'Extrayendo y normalizando audio', en: 'Extracting and normalizing audio' },
  'stage.transcription': { es: 'Transcribiendo con Whisper', en: 'Transcribing with Whisper' },
  'stage.diarization': { es: 'Detectando speakers', en: 'Detecting speakers' },
  'stage.merge': { es: 'Fusionando segmentos', en: 'Merging segments' },
  'stage.correction': { es: 'Corrigiendo texto', en: 'Correcting text' },
  'stage.summary': { es: 'Generando resumen', en: 'Generating summary' },
  'stage.done': { es: 'Completado', en: 'Completed' },
  'stage.failed': { es: 'Error de procesamiento', en: 'Processing error' },
  'stage.interrupted': { es: 'Interrumpido por reinicio', en: 'Interrupted by restart' },

  // ── ResultsScreen ──
  'results.transcript': { es: 'Transcripcion', en: 'Transcript' },
  'results.original': { es: 'Original', en: 'Original' },
  'results.corrected': { es: 'Corregido', en: 'Corrected' },
  'results.noTranscript': { es: 'Sin transcript disponible.', en: 'No transcript available.' },
  'results.speakers': { es: 'Speakers', en: 'Speakers' },
  'results.noSpeakers': { es: 'Sin speakers detectados.', en: 'No speakers detected.' },
  'results.actions': { es: 'Acciones', en: 'Actions' },
  'results.correcting': { es: 'Corrigiendo...', en: 'Correcting...' },
  'results.correctedDone': { es: 'Corregido', en: 'Corrected' },
  'results.correctTranscript': { es: 'Corregir transcripcion', en: 'Correct transcript' },
  'results.generating': { es: 'Generando...', en: 'Generating...' },
  'results.summaryReady': { es: 'Resumen listo', en: 'Summary ready' },
  'results.generateSummary': { es: 'Generar resumen', en: 'Generate summary' },
  'results.summaryOverview': { es: 'Resumen', en: 'Summary' },
  'results.keyPoints': { es: 'Puntos clave', en: 'Key points' },
  'results.decisions': { es: 'Decisiones', en: 'Decisions' },
  'results.topics': { es: 'Temas', en: 'Topics' },
  'results.noOverview': { es: 'Sin resumen.', en: 'No summary.' },
  'results.noKeyPoints': { es: 'Sin puntos clave.', en: 'No key points.' },
  'results.noDecisions': { es: 'Sin decisiones.', en: 'No decisions.' },
  'results.noTopics': { es: 'Sin temas.', en: 'No topics.' },
  'results.generateHint': { es: 'Genera un resumen\npara ver puntos clave.', en: 'Generate a summary\nto see key points.' },
  'results.export': { es: 'Exportar', en: 'Export' },
  'results.saving': { es: 'Guardando...', en: 'Saving...' },

  // ── ExportScreen ──
  'export.title': { es: 'Exportar resultados', en: 'Export results' },
  'export.formats': { es: 'Formatos', en: 'Formats' },
  'export.timestamps': { es: 'Incluir marcas de tiempo', en: 'Include timestamps' },
  'export.run': { es: 'Exportar', en: 'Export' },
  'export.exporting': { es: 'Exportando...', en: 'Exporting...' },
  'export.done': { es: 'Exportacion completa', en: 'Export complete' },
  'export.openFolder': { es: 'Abrir carpeta', en: 'Open folder' },
  'export.newProject': { es: 'Nuevo proyecto', en: 'New project' },

  // ── SettingsScreen ──
  'settings.title': { es: 'Configuracion', en: 'Settings' },
  'settings.save': { es: 'Guardar', en: 'Save' },
  'settings.saved': { es: 'Guardado', en: 'Saved' },

  // ── ProcessingScreen ──
  'processing.title': { es: 'Procesando', en: 'Processing' },
  'processing.noName': { es: 'Archivo sin nombre', en: 'Unnamed file' },
  'processing.waitingPipeline': { es: 'Esperando inicio del pipeline...', en: 'Waiting for pipeline to start...' },
  'processing.confirmCancel': { es: 'El procesamiento esta en curso. Seguro que quieres cancelar?', en: 'Processing is in progress. Are you sure you want to cancel?' },
  'processing.confirmTitle': { es: 'Cancelar procesamiento', en: 'Cancel processing' },
  'processing.confirmYes': { es: 'Si, cancelar', en: 'Yes, cancel' },
  'processing.confirmNo': { es: 'Continuar', en: 'Continue' },
  'processing.cancelBack': { es: 'Cancelar y volver al inicio', en: 'Cancel and go back' },
  'processing.etaRemaining': { es: 'restantes', en: 'remaining' },
  'processing.step.validating': { es: 'Validando archivo', en: 'Validating file' },
  'processing.step.audio': { es: 'Preparando audio', en: 'Preparing audio' },
  'processing.step.transcription': { es: 'Transcribiendo', en: 'Transcribing' },
  'processing.step.diarization': { es: 'Detectando speakers', en: 'Detecting speakers' },
  'processing.step.merge': { es: 'Fusionando segmentos', en: 'Merging segments' },
  'processing.step.correction': { es: 'Corrigiendo texto', en: 'Correcting text' },
  'processing.step.summary': { es: 'Generando resumen', en: 'Generating summary' },

  // ── ExportScreen (extra) ──
  'export.backResults': { es: 'Volver a resultados', en: 'Back to results' },
  'export.heading': { es: 'Exportar transcripcion', en: 'Export transcript' },
  'export.formatLabel': { es: 'Formato', en: 'Format' },
  'export.includeTimestamps': { es: 'Incluir timestamps', en: 'Include timestamps' },
  'export.willExport': { es: 'Se exportara', en: 'Will export' },
  'export.correctedTranscript': { es: 'Transcripcion corregida', en: 'Corrected transcript' },
  'export.originalTranscript': { es: 'Transcripcion original', en: 'Original transcript' },
  'export.summaryIncluded': { es: 'Resumen incluido', en: 'Summary included' },
  'export.completed': { es: 'Exportacion completada', en: 'Export complete' },
  'export.openFile': { es: 'Abrir archivo', en: 'Open file' },
  'export.viewFolder': { es: 'Ver en carpeta', en: 'View in folder' },
  'export.open': { es: 'Abrir', en: 'Open' },
  'export.folder': { es: 'Carpeta', en: 'Folder' },
  'export.newTranscription': { es: 'Iniciar nueva transcripcion', en: 'Start new transcription' },
  'export.errorTitle': { es: 'Error al exportar', en: 'Export error' },
  'export.retry': { es: 'Reintentar', en: 'Retry' },
  'export.exportBtn': { es: 'Exportar', en: 'Export' },
  'export.exportingBtn': { es: 'Exportando...', en: 'Exporting...' },
  'export.failedExport': { es: 'No se pudo exportar.', en: 'Export failed.' },
  'export.failedOpenFile': { es: 'No se pudo abrir el archivo.', en: 'Could not open file.' },
  'export.failedOpenFolder': { es: 'No se pudo abrir la carpeta.', en: 'Could not open folder.' },
  'export.descTxt': { es: 'Texto plano', en: 'Plain text' },
  'export.descMd': { es: 'Markdown', en: 'Markdown' },
  'export.descJson': { es: 'Estructurado', en: 'Structured' },
  'export.descPdf': { es: 'Documento', en: 'Document' },
  'export.descDocx': { es: 'Word', en: 'Word' },

  // ── SettingsScreen ──
  'settings.back': { es: 'Volver', en: 'Back' },
  'settings.heading': { es: 'Configuracion', en: 'Settings' },
  'settings.subtitle': { es: 'Ajustes del sistema. Se guardan en config/default.yaml.', en: 'System settings. Saved in config/default.yaml.' },
  'settings.aiModels': { es: 'Modelos de IA', en: 'AI Models' },
  'settings.refresh': { es: 'Actualizar', en: 'Refresh' },
  'settings.whisperSection': { es: 'Transcripción (Whisper)', en: 'Transcription (Whisper)' },
  'settings.loading': { es: 'Cargando...', en: 'Loading...' },
  'settings.download': { es: 'Descargar', en: 'Download' },
  'settings.incompatible': { es: 'Incompatible', en: 'Incompatible' },
  'settings.llmSection': { es: 'Corrección y resumen (LLM)', en: 'Correction & summary (LLM)' },
  'settings.diarization': { es: 'Diarizacion Local', en: 'Local Diarization' },
  'settings.diar.fast': { es: 'Rapido', en: 'Fast' },
  'settings.diar.fastNote': { es: 'Menos uso de CPU/RAM, menor precision en cambios cortos.', en: 'Less CPU/RAM usage, lower accuracy on short turns.' },
  'settings.diar.balanced': { es: 'Equilibrado', en: 'Balanced' },
  'settings.diar.balancedNote': { es: 'Balance recomendado entre calidad y velocidad.', en: 'Recommended balance between quality and speed.' },
  'settings.diar.quality': { es: 'Calidad', en: 'Quality' },
  'settings.diar.qualityNote': { es: 'Mayor precision en speakers, mas costo de CPU.', en: 'Higher speaker accuracy, more CPU cost.' },
  'settings.whisperConfig': { es: 'Transcripcion (Whisper)', en: 'Transcription (Whisper)' },
  'settings.model': { es: 'Modelo', en: 'Model' },
  'settings.modelHint': { es: 'tiny/base = rapido · small/medium = equilibrado · large = preciso (requiere mas RAM)', en: 'tiny/base = fast · small/medium = balanced · large = accurate (needs more RAM)' },
  'settings.computeType': { es: 'Tipo de computo', en: 'Compute type' },
  'settings.compute.recommended': { es: 'Recomendado', en: 'Recommended' },
  'settings.compute.recommendedNote': { es: 'Compatible en la mayoria de equipos (CPU/GPU) con buen rendimiento.', en: 'Compatible with most hardware (CPU/GPU) with good performance.' },
  'settings.compute.gpuFast': { es: 'GPU rapido', en: 'GPU fast' },
  'settings.compute.gpuFastNote': { es: 'Usa CUDA para acelerar. Si no hay GPU compatible conviene Recomendado.', en: 'Uses CUDA for speed. If no compatible GPU, use Recommended.' },
  'settings.compute.maxPrecision': { es: 'Maxima precision', en: 'Max precision' },
  'settings.compute.maxPrecisionNote': { es: 'Mas uso de memoria y tiempo de proceso.', en: 'More memory usage and processing time.' },
  'settings.llmConfig': { es: 'Modelo LLM (Correccion y Resumen)', en: 'LLM Model (Correction & Summary)' },
  'settings.llmPath': { es: 'Ruta del modelo (.gguf)', en: 'Model path (.gguf)' },
  'settings.contextTokens': { es: 'Contexto (tokens)', en: 'Context (tokens)' },
  'settings.cpuThreads': { es: 'Threads CPU', en: 'CPU Threads' },
  'settings.storage': { es: 'Almacenamiento', en: 'Storage' },
  'settings.workDir': { es: 'Directorio de trabajo', en: 'Working directory' },
  'settings.workDirHint': { es: 'Donde se guardan proyectos, transcripciones y exports. Ruta relativa o absoluta.', en: 'Where projects, transcripts and exports are saved. Relative or absolute path.' },
  'settings.window': { es: 'Ventana', en: 'Window' },
  'settings.fullscreenMaximize': { es: 'Maximizar en pantalla completa', en: 'Maximize as fullscreen' },
  'settings.fullscreenMaximizeHint': { es: 'Si esta activo, el boton de maximizar usa fullscreen (tapa la barra de Windows).', en: 'If enabled, maximize uses fullscreen (covers Windows taskbar).' },
  'settings.fullscreenToggle': { es: 'Alternar fullscreen al maximizar', en: 'Toggle fullscreen on maximize' },
  'settings.saving': { es: 'Guardando...', en: 'Saving...' },
  'settings.savedDone': { es: 'Guardado', en: 'Saved' },
  'settings.saveChanges': { es: 'Guardar cambios', en: 'Save changes' },
  'settings.saveFailed': { es: 'No se pudo guardar la configuracion.', en: 'Could not save settings.' },

  // ── Misc ──
  'nav.settings': { es: 'Configuracion', en: 'Settings' },
  'nav.home': { es: 'Inicio', en: 'Home' },
  'nav.help': { es: 'Ayuda (proximamente)', en: 'Help (coming soon)' },
  'nav.drag': { es: 'Arrastrar para mover', en: 'Drag to move' },
  'error.connection': { es: 'No se pudo conectar con el backend. Verifica que el servidor este ejecutandose.', en: 'Could not connect to the backend. Check that the server is running.' },
  'error.timeout': { es: 'el servidor no respondio', en: 'server did not respond' },
  'error.path': { es: 'Debes ingresar la ruta local del archivo.', en: 'Enter the local file path.' },
  'processing.cancel': { es: 'Cancelar', en: 'Cancel' },
  'processing.pipelineComplete': { es: 'Pipeline completado. Cargando resultados...', en: 'Pipeline complete. Loading results...' },
};

export const translate = (key: string, lang: Lang): string => {
  const entry = t[key];
  if (!entry) return key;
  return entry[lang] || entry.es || key;
};
