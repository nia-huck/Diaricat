import { useAppState } from '@/context/AppContext';
import { useI18n } from '@/context/I18nContext';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Check, Clock, Loader2, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

const BASE_STEP_KEYS = [
  { id: 'validating',   key: 'processing.step.validating'   },
  { id: 'audio',        key: 'processing.step.audio'        },
  { id: 'transcription',key: 'processing.step.transcription' },
  { id: 'diarization',  key: 'processing.step.diarization'  },
  { id: 'merge',        key: 'processing.step.merge'        },
];
const LLM_STEP_KEYS = [
  { id: 'correction', key: 'processing.step.correction' },
  { id: 'summary',    key: 'processing.step.summary'    },
];

const ProcessingScreen = () => {
  const {
    fileName,
    pipelineStage,
    pipelineProgress,
    errorMessage,
    cancelProcessing,
    jobStatus,
    runCorrectionEnabled,
    runSummaryEnabled,
  } = useAppState();
  const { t } = useI18n();

  const steps = useMemo(() => {
    const next = [...BASE_STEP_KEYS];
    if (runCorrectionEnabled) next.push(LLM_STEP_KEYS[0]);
    if (runSummaryEnabled)    next.push(LLM_STEP_KEYS[1]);
    return next;
  }, [runCorrectionEnabled, runSummaryEnabled]);

  const [displayProgress, setDisplayProgress] = useState(0);
  const serverProgressRef = useRef(0);
  const startTimeRef = useRef<number>(Date.now());
  const [etaSeconds, setEtaSeconds] = useState(-1);
  const [showCancelDialog, setShowCancelDialog] = useState(false);

  const formatEta = (seconds: number): string => {
    if (seconds <= 0 || !isFinite(seconds)) return '';
    const rem = t('processing.etaRemaining');
    if (seconds < 60) return `~${Math.ceil(seconds)}s ${rem}`;
    const minutes = Math.floor(seconds / 60);
    const secs = Math.ceil(seconds % 60);
    if (minutes < 60) return `~${minutes}m ${secs > 0 ? `${secs}s` : ''} ${rem}`.trim();
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `~${hours}h ${mins > 0 ? `${mins}m` : ''} ${rem}`.trim();
  };

  // Stage progress ranges (each stage occupies a % range of the total bar)
  const stageRanges = useMemo<Record<string, [number, number]>>(() => {
    const hasCorrection = runCorrectionEnabled;
    const hasSummary = runSummaryEnabled;
    return {
      queued:        [0, 3],
      validating:    [3, 8],
      audio:         [8, 22],
      transcription: [22, 55],
      diarization:   [55, 72],
      merge:         [72, hasCorrection || hasSummary ? 80 : 97],
      correction:    [80, hasSummary ? 90 : 97],
      summary:       [90, 97],
      done:          [97, 100],
      failed:        [0, 100],
    };
  }, [runCorrectionEnabled, runSummaryEnabled]);

  // Reset start time when pipeline begins
  useEffect(() => {
    if (pipelineStage === 'queued' && pipelineProgress <= 1) {
      startTimeRef.current = Date.now();
    }
  }, [pipelineStage, pipelineProgress]);

  useEffect(() => {
    serverProgressRef.current = Math.max(serverProgressRef.current, pipelineProgress);
  }, [pipelineProgress]);

  useEffect(() => {
    if (pipelineStage === 'queued' && pipelineProgress <= 1) {
      serverProgressRef.current = pipelineProgress;
      setDisplayProgress(pipelineProgress);
      setEtaSeconds(-1);
      return;
    }
    if (jobStatus === 'done')   { serverProgressRef.current = 100; setDisplayProgress(100); setEtaSeconds(-1); return; }
    if (jobStatus === 'failed') { setDisplayProgress((prev) => Math.max(prev, serverProgressRef.current)); setEtaSeconds(-1); return; }

    const timer = window.setInterval(() => {
      setDisplayProgress((prev) => {
        const sp  = serverProgressRef.current;
        const range = stageRanges[pipelineStage] ?? [0, 100];
        const cap = range[1];
        if (prev < sp) return Math.min(sp, prev + 2.5);
        if (jobStatus === 'running' && prev < cap) return Math.min(cap, prev + 0.18);
        return prev;
      });

      const elapsed = (Date.now() - startTimeRef.current) / 1000;
      const currentProgress = serverProgressRef.current;
      if (currentProgress > 3 && currentProgress < 100 && elapsed > 2) {
        const rate = currentProgress / elapsed;
        const remaining = (100 - currentProgress) / rate;
        setEtaSeconds(remaining);
      } else {
        setEtaSeconds(-1);
      }
    }, 250);

    return () => window.clearInterval(timer);
  }, [jobStatus, pipelineStage, stageRanges]);

  const currentIndex  = steps.findIndex((s) => s.id === pipelineStage);
  const effectiveIndex = currentIndex === -1 ? 0 : currentIndex;
  const progressPct   = Math.min(Math.round(displayProgress), 100);
  const isFailed      = jobStatus === 'failed';
  const eta = formatEta(etaSeconds);

  const handleCancelClick = () => {
    if (jobStatus === 'running' || jobStatus === 'queued') {
      setShowCancelDialog(true);
    } else {
      cancelProcessing();
    }
  };

  const handleConfirmCancel = () => {
    setShowCancelDialog(false);
    cancelProcessing();
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 max-w-xl mx-auto w-full gap-5 animate-fade-in">

      {/* File info */}
      <div className="text-center space-y-1">
        <p className="font-mono text-[10px] text-primary/55 uppercase tracking-[0.14em]">{t('processing.title')}</p>
        <p className="font-display text-base font-semibold text-foreground/90 truncate max-w-sm">
          {fileName || t('processing.noName')}
        </p>
      </div>

      {/* Progress bar */}
      <div className="w-full glass-panel rounded-xl p-4 space-y-2">
        <div className="flex justify-between items-center">
          <span className="font-mono text-[10px] text-muted-foreground/45 uppercase tracking-wider">
            {pipelineStage || 'queued'}
          </span>
          <div className="flex items-center gap-2">
            {eta && (
              <span className="flex items-center gap-1 font-mono text-[10px] text-muted-foreground/40">
                <Clock className="w-2.5 h-2.5" />
                {eta}
              </span>
            )}
            <span className={`font-mono text-sm font-semibold ${isFailed ? 'text-destructive' : 'text-primary'}`}>
              {progressPct}%
            </span>
          </div>
        </div>
        <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(140,100,230,0.1)' }}>
          <div
            className={`h-full rounded-full transition-all duration-300 ease-out ${
              isFailed     ? 'bg-destructive' :
              progressPct < 100 ? 'progress-gradient' :
              'bg-primary glow-violet-sm'
            }`}
            style={{ width: `${Math.max(displayProgress, 0)}%` }}
          />
        </div>
      </div>

      {/* Timeline steps */}
      <div className="w-full glass-panel rounded-2xl p-5">
        <div className="relative">
          {/* Connecting line */}
          <div
            className="absolute left-[7px] top-3 bottom-3 w-px"
            style={{ background: 'linear-gradient(to bottom, rgba(140,100,230,0.25) 0%, rgba(140,100,230,0.06) 100%)' }}
          />

          <div className="space-y-4">
            {steps.map((step, index) => {
              const done    = index < effectiveIndex || (jobStatus === 'done' && index <= effectiveIndex);
              const active  = index === effectiveIndex && jobStatus !== 'done' && !isFailed;
              const failed  = isFailed && step.id === pipelineStage;
              const pending = !done && !active && !failed;

              return (
                <div key={step.id} className="flex items-center gap-3.5 relative">
                  {/* Dot */}
                  <div className={`w-3.5 h-3.5 rounded-full flex items-center justify-center shrink-0 z-10 transition-all duration-400 ${
                    failed  ? 'bg-destructive shadow-[0_0_10px_hsl(var(--destructive)/0.4)]' :
                    done    ? 'bg-success glow-success' :
                    active  ? 'bg-primary ring-2 ring-primary/25 shadow-[0_0_12px_hsl(var(--primary)/0.5)]' :
                    pending ? 'border border-white/10 bg-white/[0.03]' : ''
                  }`}>
                    {done   && <Check className="w-2 h-2 text-white" strokeWidth={3.5} />}
                    {failed && <X     className="w-2 h-2 text-white" strokeWidth={3} />}
                    {active && <div className="w-1.5 h-1.5 rounded-full bg-primary-foreground/90 animate-ping" />}
                  </div>

                  {/* Label */}
                  <span className={`text-sm transition-all duration-300 flex-1 ${
                    failed  ? 'text-destructive' :
                    done    ? 'text-success/50 font-mono text-[11px]' :
                    active  ? 'text-foreground font-display font-semibold' :
                    pending ? 'text-muted-foreground/28 font-mono text-[11px]' : ''
                  }`}>
                    {t(step.key)}
                  </span>

                  {active && <Loader2 className="w-3.5 h-3.5 text-primary animate-spin shrink-0" />}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {errorMessage && (
        <p className="text-xs text-destructive text-center animate-slide-up">{errorMessage}</p>
      )}

      {/* Cancel */}
      <button
        onClick={handleCancelClick}
        className="glass-control px-4 py-2 font-mono text-[11px] text-muted-foreground/50 hover:text-muted-foreground transition-colors duration-150 rounded-lg"
      >
        {t('processing.cancelBack')}
      </button>

      {/* Cancel confirmation dialog */}
      <AlertDialog open={showCancelDialog} onOpenChange={setShowCancelDialog}>
        <AlertDialogContent className="glass-panel border-white/10 sm:max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle className="font-display text-foreground">
              {t('processing.confirmTitle')}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-muted-foreground/70">
              {t('processing.confirmCancel')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="glass-control border-white/10 text-muted-foreground hover:text-foreground">
              {t('processing.confirmNo')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmCancel}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {t('processing.confirmYes')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

export default ProcessingScreen;
