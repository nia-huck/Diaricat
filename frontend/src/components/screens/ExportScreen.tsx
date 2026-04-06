import { useAppState } from '@/context/AppContext';
import { useI18n } from '@/context/I18nContext';
import { api } from '@/lib/api';
import type { ExportFormat } from '@/types/backend';
import { useMemo, useState } from 'react';
import { Download, Check, AlertCircle, ArrowLeft, FileText, FileJson, File, FolderOpen, ExternalLink } from 'lucide-react';

const FORMAT_KEYS: Record<string, string> = {
  txt: 'export.descTxt',
  md: 'export.descMd',
  json: 'export.descJson',
  pdf: 'export.descPdf',
  docx: 'export.descDocx',
};

const formats = [
  { key: 'txt' as const, label: 'TXT', icon: FileText },
  { key: 'md' as const, label: 'MD', icon: FileText },
  { key: 'json' as const, label: 'JSON', icon: FileJson },
  { key: 'pdf' as const, label: 'PDF', icon: File },
  { key: 'docx' as const, label: 'DOCX', icon: FileText },
];

const ExportScreen = () => {
  const { setScreen, fileName, corrected, summaryGenerated, exportResults, startNewProject, artifacts: contextArtifacts } = useAppState();
  const { t } = useI18n();

  const [selectedFormats, setSelectedFormats] = useState<ExportFormat[]>(['json', 'md', 'txt', 'pdf', 'docx']);
  const [includeTimestamps, setIncludeTimestamps] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportDone, setExportDone] = useState(false);
  const [openActionError, setOpenActionError] = useState<string | null>(null);
  const [openingPath, setOpeningPath] = useState<string | null>(null);

  const artifacts = exportDone && Object.keys(contextArtifacts).length > 0 ? contextArtifacts : null;

  const exportContentLabel = useMemo(() => {
    return corrected ? t('export.correctedTranscript') : t('export.originalTranscript');
  }, [corrected, t]);

  const firstArtifactPath = useMemo(() => {
    if (!artifacts) return null;
    const values = Object.values(artifacts);
    return values.length > 0 ? values[0] : null;
  }, [artifacts]);

  const toggleFormat = (value: ExportFormat) => {
    setSelectedFormats((prev) => {
      if (prev.includes(value)) {
        if (prev.length === 1) return prev;
        return prev.filter((f) => f !== value);
      }
      return [...prev, value];
    });
  };

  const handleExport = async () => {
    try {
      setExporting(true);
      setExportError(null);
      setOpenActionError(null);
      await exportResults(selectedFormats, includeTimestamps);
      setExportDone(true);
    } catch (error) {
      setExportError(error instanceof Error ? error.message : t('export.failedExport'));
    } finally {
      setExporting(false);
    }
  };

  const handleOpenFile = async (path: string) => {
    try {
      setOpeningPath(path);
      setOpenActionError(null);
      await api.openFile(path);
    } catch (error) {
      setOpenActionError(error instanceof Error ? error.message : t('export.failedOpenFile'));
    } finally {
      setOpeningPath(null);
    }
  };

  const handleOpenFolder = async (path: string) => {
    try {
      setOpeningPath(path);
      setOpenActionError(null);
      await api.openFolder(path);
    } catch (error) {
      setOpenActionError(error instanceof Error ? error.message : t('export.failedOpenFolder'));
    } finally {
      setOpeningPath(null);
    }
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center pt-[60px] px-8 pb-8 max-w-xl mx-auto w-full gap-5 animate-fade-in">
      <button
        onClick={() => setScreen('results')}
        className="self-start glass-control flex items-center gap-1.5 text-xs text-muted-foreground/60 hover:text-foreground transition-colors duration-150 px-3 py-1.5"
      >
        <ArrowLeft className="w-3 h-3" />
        {t('export.backResults')}
      </button>

      <div className="text-center">
        <h2 className="font-display text-base font-semibold text-foreground/92">{t('export.heading')}</h2>
        <p className="text-xs text-muted-foreground/50 mt-0.5 font-mono truncate max-w-xs">{fileName}</p>
      </div>

      {/* Format selector */}
      <div className="w-full space-y-2">
        <p className="text-[11px] text-muted-foreground/40 uppercase tracking-widest font-medium pl-0.5">{t('export.formatLabel')}</p>
        <div className="grid grid-cols-5 gap-2">
          {formats.map((format) => {
            const selected = selectedFormats.includes(format.key);
            return (
              <button
                key={format.key}
                onClick={() => toggleFormat(format.key)}
                className={`flex flex-col items-center gap-1.5 p-3 rounded-xl border text-xs transition-all duration-150 ${
                  selected
                    ? 'border-primary/50 bg-primary/10 text-foreground glow-violet-sm'
                    : 'glass-control border-border/40 text-muted-foreground/60 hover:border-primary/25 hover:bg-primary/5'
                }`}
              >
                <format.icon className={`w-4 h-4 ${selected ? 'text-primary' : 'text-muted-foreground/40'}`} />
                <span className={`font-semibold text-[11px] ${selected ? 'text-foreground' : ''}`}>{format.label}</span>
                <span className="text-[10px] text-muted-foreground/40 leading-none">{t(FORMAT_KEYS[format.key])}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Options */}
      <div className="w-full">
        <label className="glass-panel flex items-center gap-3 p-3 rounded-xl cursor-pointer hover:border-primary/20 hover:bg-primary/5 transition-all duration-150 group">
          <input
            type="checkbox"
            checked={includeTimestamps}
            onChange={(e) => setIncludeTimestamps(e.target.checked)}
            className="accent-[hsl(var(--primary))] w-3.5 h-3.5"
          />
          <span className="text-xs text-foreground/80">{t('export.includeTimestamps')}</span>
        </label>
      </div>

      {/* Summary card */}
      <div className="w-full glass-panel rounded-xl p-4 space-y-1.5">
        <p className="text-[11px] text-muted-foreground/40 uppercase tracking-widest font-medium mb-2">{t('export.willExport')}</p>
        <div className="flex items-center gap-2 text-xs text-foreground/70">
          <Check className="w-3 h-3 text-success shrink-0" />
          {exportContentLabel}
        </div>
        {summaryGenerated && (
          <div className="flex items-center gap-2 text-xs text-foreground/70">
            <Check className="w-3 h-3 text-success shrink-0" />
            {t('export.summaryIncluded')}
          </div>
        )}
        <div className="flex items-center gap-2 text-xs text-foreground/70">
          <Check className="w-3 h-3 text-success shrink-0" />
          <span className="font-mono">{selectedFormats.join(' · ').toUpperCase()}</span>
        </div>
      </div>

      {/* Result / CTA */}
      {artifacts ? (
        <div className="w-full glass-panel rounded-2xl p-4 space-y-3 animate-slide-up border border-success/25">
          <p className="text-sm font-medium text-success">{t('export.completed')}</p>

          {firstArtifactPath && (
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => void handleOpenFile(firstArtifactPath)}
                disabled={openingPath === firstArtifactPath}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs hover:bg-primary/90 disabled:opacity-50 btn-glow transition-all"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                {t('export.openFile')}
              </button>
              <button
                onClick={() => void handleOpenFolder(firstArtifactPath)}
                disabled={openingPath === firstArtifactPath}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg glass-control border border-border/50 text-secondary-foreground text-xs hover:bg-secondary transition-all"
              >
                <FolderOpen className="w-3.5 h-3.5" />
                {t('export.viewFolder')}
              </button>
            </div>
          )}

          <div className="space-y-2">
            {Object.entries(artifacts).map(([key, path]) => (
              <div key={key} className="border border-border/30 rounded-lg p-2.5 bg-card/30">
                <p className="text-xs text-muted-foreground/60 break-all leading-relaxed">
                  <span className="text-foreground/70 font-medium font-mono">{key.toUpperCase()}</span>
                  {' · '}
                  <span className="font-mono">{path}</span>
                </p>
                <div className="mt-2 flex gap-1.5">
                  <button
                    onClick={() => void handleOpenFile(path)}
                    disabled={openingPath === path}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] bg-primary/15 text-primary hover:bg-primary/25 disabled:opacity-50 transition-all"
                  >
                    <ExternalLink className="w-2.5 h-2.5" />
                    {t('export.open')}
                  </button>
                  <button
                    onClick={() => void handleOpenFolder(path)}
                    disabled={openingPath === path}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] bg-secondary/60 text-secondary-foreground hover:bg-secondary transition-all"
                  >
                    <FolderOpen className="w-2.5 h-2.5" />
                    {t('export.folder')}
                  </button>
                </div>
              </div>
            ))}
          </div>

          {openActionError && <p className="text-xs text-destructive">{openActionError}</p>}

          <button onClick={startNewProject} className="text-xs text-primary hover:underline underline-offset-2 transition-colors">
            {t('export.newTranscription')}
          </button>
        </div>
      ) : exportError ? (
        <div className="w-full glass-panel border border-destructive/25 rounded-2xl p-5 text-center animate-slide-up">
          <AlertCircle className="w-5 h-5 text-destructive mx-auto mb-2" />
          <p className="text-sm font-medium text-destructive">{t('export.errorTitle')}</p>
          <p className="text-xs text-muted-foreground/60 mt-1">{exportError}</p>
          <button onClick={() => void handleExport()} className="mt-3 text-xs text-primary hover:underline underline-offset-2">
            {t('export.retry')}
          </button>
        </div>
      ) : (
        <button
          onClick={() => void handleExport()}
          disabled={exporting || selectedFormats.length === 0}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 btn-glow transition-all duration-200"
        >
          {exporting ? (
            <>
              <div className="w-4 h-4 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" />
              {t('export.exportingBtn')}
            </>
          ) : (
            <>
              <Download className="w-4 h-4" />
              {t('export.exportBtn')}
            </>
          )}
        </button>
      )}
    </div>
  );
};

export default ExportScreen;
