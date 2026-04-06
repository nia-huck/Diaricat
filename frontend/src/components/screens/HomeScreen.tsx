import { useAppState } from '@/context/AppContext';
import { useI18n } from '@/context/I18nContext';
import { api } from '@/lib/api';
import { AlertCircle, Clock, Cpu, FolderOpen, MonitorSpeaker, Play, Upload, Zap } from 'lucide-react';
import { useRef, useState, type ChangeEvent, type DragEvent } from 'react';

const RECENTS_KEY = 'diaricat.recentPaths';
const ACCEPTED_EXTENSIONS = ['.mp4', '.mp3', '.wav', '.mkv', '.m4a'];

const HomeScreen = () => {
  const {
    filePath,
    computeMode,
    setComputeMode,
    startPipeline,
    errorMessage,
    clearError,
    isBusy,
  } = useAppState();
  const { t } = useI18n();

  const [sourcePath, setSourcePath] = useState(filePath);
  const [dragOver, setDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [recentPaths, setRecentPaths] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem(RECENTS_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw) as string[];
      return Array.isArray(parsed) ? parsed.slice(0, 5) : [];
    } catch { return []; }
  });

  const persistRecent = (path: string) => {
    setRecentPaths((prev) => {
      const all = [path, ...prev.filter((p) => p !== path)].slice(0, 5);
      try { localStorage.setItem(RECENTS_KEY, JSON.stringify(all)); } catch { /* ignore */ }
      return all;
    });
  };

  const setSelectedPath = (path: string) => {
    setSourcePath(path);
    if (errorMessage) clearError();
    setUploadError(null);
  };

  const uploadLocalFile = async (file: File) => {
    setIsUploading(true);
    setUploadError(null);
    setUploadMessage(`Subiendo ${file.name}...`);
    try {
      const response = await api.uploadFile(file);
      setSelectedPath(response.stored_path);
      setUploadMessage(`Listo: ${response.original_name}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'No se pudo cargar el archivo.';
      setUploadError(message);
      setUploadMessage(null);
    } finally {
      setIsUploading(false);
    }
  };

  const openFilePicker = () => fileInputRef.current?.click();

  const onFileInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    const first = event.target.files?.[0];
    if (first) void uploadLocalFile(first);
    event.target.value = '';
  };

  const launch = () => {
    if (!sourcePath.trim()) return;
    clearError();
    persistRecent(sourcePath.trim());
    void startPipeline(sourcePath.trim());
  };

  const isAcceptedFile = (file: File): boolean => {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    return ACCEPTED_EXTENSIONS.includes(ext);
  };

  const onDropFile = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragOver(false);
    const first = event.dataTransfer.files?.[0];
    if (first) {
      if (!isAcceptedFile(first)) {
        setUploadError(`Formato no soportado. Usa: ${ACCEPTED_EXTENSIONS.join(', ')}`);
        return;
      }
      void uploadLocalFile(first);
      return;
    }
    const fallback = event.dataTransfer.getData('text/plain');
    if (fallback) { setSelectedPath(fallback); setUploadMessage(null); }
  };

  const modes = [
    { key: 'auto' as const, label: 'Auto', icon: Zap },
    { key: 'cpu'  as const, label: 'CPU',  icon: Cpu },
    { key: 'gpu'  as const, label: 'GPU',  icon: MonitorSpeaker },
  ];

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 max-w-2xl mx-auto w-full gap-5 animate-fade-in">
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        accept={ACCEPTED_EXTENSIONS.join(',')}
        onChange={onFileInputChange}
      />

      {/* Drop zone */}
      <div
        className={`w-full cursor-pointer transition-all duration-300 p-10 flex flex-col items-center gap-4 ${
          dragOver ? 'drag-zone drag-zone-active' : 'drag-zone'
        }`}
        role="button"
        tabIndex={0}
        onClick={openFilePicker}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openFilePicker(); } }}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDropFile}
      >
        {/* Upload icon */}
        <div className={`w-16 h-16 rounded-2xl flex items-center justify-center transition-all duration-300 ${
          dragOver
            ? 'bg-primary/20 shadow-[0_0_28px_hsl(var(--primary)/0.35)]'
            : 'glass-control'
        }`}>
          <Upload className={`w-7 h-7 transition-all duration-300 ${
            dragOver ? 'text-primary scale-110' : 'text-primary/55'
          }`} />
        </div>

        <div className="text-center space-y-1.5">
          <p className="font-display text-sm font-semibold text-foreground/90">
            {t('home.dropzone')}{' '}
            <span className="text-primary">{t('home.select')}</span>
          </p>
          <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/40">
            .mp4 · .mp3 · .wav · .mkv · .m4a
          </p>
        </div>

        {isUploading && (
          <p className="text-xs text-muted-foreground/60 animate-pulse font-mono">
            {t('home.uploading')}
          </p>
        )}
        {uploadMessage && !uploadError && (
          <p className="text-xs text-primary/75 animate-slide-up">{uploadMessage}</p>
        )}
        {uploadError && (
          <p className="text-xs text-destructive animate-slide-up flex items-center gap-1.5">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            {uploadError}
          </p>
        )}
      </div>

      {/* Path input + launch */}
      <div className="w-full space-y-1.5">
        <div className="flex gap-2">
          <input
            value={sourcePath}
            onChange={(e) => {
              setSourcePath(e.target.value);
              if (errorMessage) clearError();
              setUploadError(null);
              setUploadMessage(null);
            }}
            onKeyDown={(e) => { if (e.key === 'Enter') launch(); }}
            placeholder={t('home.pathPlaceholder')}
            className="flex-1 font-mono text-xs glass-control rounded-xl px-4 py-3 outline-none focus:shadow-[0_0_0_1px_hsl(var(--primary)/0.4),0_0_20px_hsl(var(--primary)/0.1)] placeholder:text-muted-foreground/30 transition-all duration-200 text-foreground/85"
          />
          <button
            onClick={launch}
            disabled={!sourcePath.trim() || isBusy || isUploading}
            className="px-5 py-3 rounded-xl bg-primary text-primary-foreground text-sm font-semibold font-display flex items-center gap-2 hover:bg-primary/90 disabled:opacity-35 disabled:cursor-not-allowed btn-glow breathing transition-all duration-200"
          >
            <Play className="w-4 h-4" />
            {t('home.start')}
          </button>
        </div>
        {errorMessage && (
          <p className="text-xs text-destructive flex items-center gap-1.5 pl-1 animate-slide-up">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            {errorMessage}
          </p>
        )}
      </div>

      {/* Compute mode */}
      <div className="w-full space-y-2">
        <p className="font-mono text-[10px] text-muted-foreground/35 uppercase tracking-[0.14em] pl-0.5">
          {t('home.compute')}
        </p>
        <div className="flex gap-2">
          {modes.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setComputeMode(key)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-medium transition-all duration-200 ${
                computeMode === key
                  ? 'bg-primary text-primary-foreground glow-violet-sm font-semibold'
                  : 'glass-control text-muted-foreground/65 hover:text-foreground'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Recents */}
      <div className="w-full space-y-2">
        <p className="font-mono text-[10px] text-muted-foreground/35 uppercase tracking-[0.14em] pl-0.5">
          {t('home.recent')}
        </p>
        <div className="glass-panel rounded-xl overflow-hidden divide-y divide-white/[0.04]">
          {recentPaths.length === 0 ? (
            <div className="px-4 py-4 font-mono text-[11px] text-muted-foreground/30">
              {t('home.noRecent')}
            </div>
          ) : (
            recentPaths.map((path) => (
              <button
                key={path}
                onClick={() => setSourcePath(path)}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-primary/[0.06] transition-colors duration-150 text-left group"
              >
                <FolderOpen className="w-3.5 h-3.5 text-primary/40 group-hover:text-primary/70 shrink-0 transition-colors" />
                <span className="font-mono text-xs flex-1 truncate text-muted-foreground/55 group-hover:text-foreground/75 transition-colors">
                  {path}
                </span>
                <span className="font-mono text-[10px] text-muted-foreground/25 flex items-center gap-1 shrink-0 group-hover:text-muted-foreground/45 transition-colors">
                  <Clock className="w-2.5 h-2.5" />
                  {t('home.reuse')}
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

export default HomeScreen;
