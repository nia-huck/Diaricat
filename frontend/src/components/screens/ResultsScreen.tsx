import { useAppState } from '@/context/AppContext';
import { useI18n } from '@/context/I18nContext';
import { useMemo, useState } from 'react';
import { Check, Edit3, FileText, Loader2, Sparkles, ArrowRight, AlertCircle, ChevronRight } from 'lucide-react';

const toTimestamp = (value: number): string => {
  const total = Math.max(Math.floor(value), 0);
  const h = Math.floor(total / 3600).toString().padStart(2, '0');
  const m = Math.floor((total % 3600) / 60).toString().padStart(2, '0');
  const s = Math.floor(total % 60).toString().padStart(2, '0');
  return `${h}:${m}:${s}`;
};

const SPEAKER_COLORS = [
  { hsl: 'hsl(263 75% 65%)', hex: '#9b6bdf' },
  { hsl: 'hsl(195 80% 55%)', hex: '#29b5d4' },
  { hsl: 'hsl(340 75% 60%)', hex: '#e04d79' },
  { hsl: 'hsl(42 90% 58%)',  hex: '#e8a82a' },
  { hsl: 'hsl(160 65% 50%)', hex: '#3fc28a' },
  { hsl: 'hsl(20 85% 58%)',  hex: '#e06d3a' },
];

const getSpeakerColor = (index: number) => SPEAKER_COLORS[index % SPEAKER_COLORS.length];

const SpeakerAvatar = ({ name, color }: { name: string; color: typeof SPEAKER_COLORS[0] }) => {
  const initial = name.charAt(0).toUpperCase();
  return (
    <span
      className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold shrink-0 select-none"
      style={{
        background: `${color.hex}22`,
        border: `1px solid ${color.hex}55`,
        color: color.hsl,
      }}
    >
      {initial}
    </span>
  );
};

const ResultsScreen = () => {
  const {
    setScreen,
    speakers,
    viewMode,
    setViewMode,
    corrected,
    summaryGenerated,
    transcriptSegments,
    summary,
    renameSpeaker,
    runCorrection,
    runSummary,
    pipelineStage,
    isBusy,
    errorMessage,
  } = useAppState();

  const { t } = useI18n();
  const [editingSpeaker, setEditingSpeaker] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [selectedBlock, setSelectedBlock] = useState(0);
  const [isSaving, setIsSaving] = useState(false);

  const speakerColorMap = useMemo(() => {
    const map: Record<string, number> = {};
    Object.keys(speakers).forEach((id, i) => { map[id] = i; });
    return map;
  }, [speakers]);

  const data = useMemo(
    () =>
      transcriptSegments.map((seg) => ({
        ...seg,
        renderedText:
          viewMode === 'corrected' && corrected
            ? seg.text_corrected?.trim() || seg.text_raw
            : seg.text_raw,
      })),
    [corrected, transcriptSegments, viewMode]
  );

  const saveEdit = async () => {
    if (!editingSpeaker) return;
    const value = editValue.trim();
    if (!value) { setEditingSpeaker(null); return; }
    setIsSaving(true);
    try { await renameSpeaker(editingSpeaker, value); }
    finally { setIsSaving(false); setEditingSpeaker(null); }
  };

  const runningCorrection = isBusy && pipelineStage === 'correction';
  const runningSummary    = isBusy && pipelineStage === 'summary';

  const summaryItems = summaryGenerated && summary ? [
    { title: t('results.summaryOverview'), content: summary.overview ? [summary.overview] : [t('results.noOverview')] },
    { title: t('results.keyPoints'),       content: summary.key_points.length ? summary.key_points : [t('results.noKeyPoints')] },
    { title: t('results.decisions'),       content: summary.decisions.length  ? summary.decisions  : [t('results.noDecisions')] },
    { title: t('results.topics'),          content: summary.topics.length     ? summary.topics     : [t('results.noTopics')] },
  ] : null;

  return (
    <div className="flex-1 flex overflow-hidden animate-fade-in pt-14 px-3 pb-3 gap-3">

      {/* ── Transcript panel ───────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden glass-panel rounded-2xl">

        {/* Header */}
        <div className="px-5 py-3 border-b border-white/[0.06] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <FileText className="w-3.5 h-3.5 text-primary/60" />
            <span className="text-xs font-semibold text-white/70 tracking-wide">{t('results.transcript')}</span>
          </div>

          {/* Toggle pill */}
          <div className="results-toggle">
            <button
              onClick={() => setViewMode('original')}
              className={`results-toggle-btn ${viewMode === 'original' ? 'results-toggle-btn--active' : ''}`}
            >
              {t('results.original')}
            </button>
            <button
              onClick={() => setViewMode('corrected')}
              disabled={!corrected}
              className={`results-toggle-btn ${
                viewMode === 'corrected' ? 'results-toggle-btn--active' : ''
              } disabled:opacity-30 disabled:cursor-not-allowed`}
            >
              {t('results.corrected')}
            </button>
          </div>
        </div>

        {/* Segments */}
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-1.5 results-scroll">
          {data.length === 0 && (
            <div className="p-6 text-xs text-white/25 text-center">{t('results.noTranscript')}</div>
          )}
          {data.map((block, index) => {
            const colorIdx = speakerColorMap[block.speaker_id] ?? 0;
            const color    = getSpeakerColor(colorIdx);
            const isSelected = selectedBlock === index;
            const speakerName = speakers[block.speaker_id] || block.speaker_id;

            return (
              <div
                key={`${block.start}-${block.end}-${index}`}
                role="button"
                tabIndex={0}
                onClick={() => setSelectedBlock(index)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setSelectedBlock(index);
                  }
                }}
                className={`segment-block ${isSelected ? 'segment-block--selected' : ''}`}
                style={{ '--sp-color': color.hex } as React.CSSProperties}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <span
                    className="w-1 h-full absolute left-0 top-0 bottom-0 rounded-l-xl"
                    style={{ background: color.hex, opacity: isSelected ? 0.7 : 0.35 }}
                  />
                  <SpeakerAvatar name={speakerName} color={color} />
                  <span className="text-[11px] font-semibold" style={{ color: color.hsl }}>
                    {speakerName}
                  </span>
                  <span className="text-[10px] text-white/25 font-mono ml-auto tabular-nums">
                    {toTimestamp(block.start)}
                  </span>
                </div>
                <p className="text-[13px] leading-relaxed text-white/75 pl-7">{block.renderedText}</p>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Side panel ─────────────────────────────────── */}
      <div className="w-72 flex flex-col overflow-hidden shrink-0 glass-panel rounded-2xl">

        {/* Speakers */}
        <div className="px-4 pt-4 pb-3 border-b border-white/[0.06]">
          <p className="sidebar-section-label">{t('results.speakers')}</p>
          <div className="space-y-2 mt-2.5">
            {Object.entries(speakers).length === 0 && (
              <p className="text-xs text-white/25">{t('results.noSpeakers')}</p>
            )}
            {Object.entries(speakers).map(([speakerId, name], i) => {
              const color = getSpeakerColor(i);
              return (
                <div key={speakerId} className="flex items-center gap-2">
                  <SpeakerAvatar name={name} color={color} />
                  {editingSpeaker === speakerId ? (
                    <input
                      autoFocus
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onBlur={() => void saveEdit()}
                      onKeyDown={(e) => { if (e.key === 'Enter') void saveEdit(); }}
                      className="flex-1 text-xs bg-white/[0.06] border border-primary/30 rounded-lg px-2 py-1 outline-none focus:ring-1 focus:ring-primary/30 text-white/80"
                    />
                  ) : (
                    <button
                      onClick={() => { setEditingSpeaker(speakerId); setEditValue(name); }}
                      className="flex-1 text-left text-xs flex items-center gap-1.5 group/sp"
                    >
                      <span className="text-white/70 group-hover/sp:text-white transition-colors">{name}</span>
                      <Edit3 className="w-2.5 h-2.5 text-white/20 opacity-0 group-hover/sp:opacity-100 transition-opacity ml-auto" />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Actions */}
        <div className="px-4 py-3 border-b border-white/[0.06] space-y-2">
          <p className="sidebar-section-label">{t('results.actions')}</p>
          <button
            onClick={() => void runCorrection()}
            disabled={corrected || isBusy}
            className="sidebar-action-btn sidebar-action-btn--primary"
          >
            {runningCorrection ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : corrected ? (
              <Check className="w-3.5 h-3.5" />
            ) : (
              <Sparkles className="w-3.5 h-3.5" />
            )}
            {runningCorrection ? t('results.correcting') : corrected ? t('results.correctedDone') : t('results.correctTranscript')}
          </button>

          <button
            onClick={() => void runSummary()}
            disabled={summaryGenerated || isBusy}
            className="sidebar-action-btn sidebar-action-btn--secondary"
          >
            {runningSummary ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : summaryGenerated ? (
              <Check className="w-3.5 h-3.5" />
            ) : (
              <FileText className="w-3.5 h-3.5" />
            )}
            {runningSummary ? t('results.generating') : summaryGenerated ? t('results.summaryReady') : t('results.generateSummary')}
          </button>
        </div>

        {/* Summary */}
        <div className="flex-1 overflow-y-auto px-4 py-3 results-scroll">
          {summaryItems ? (
            <div className="space-y-4 animate-slide-up">
              {summaryItems.map(({ title, content }) => (
                <div key={title}>
                  <p className="sidebar-section-label mb-2">{title}</p>
                  <ul className="space-y-1.5">
                    {content.map((item, i) => (
                      <li key={i} className="flex items-start gap-2 text-[12px] text-white/60 leading-relaxed">
                        <ChevronRight className="w-3 h-3 text-primary/50 mt-0.5 shrink-0" />
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center h-full">
              <p className="text-[11px] text-white/25 text-center leading-relaxed whitespace-pre-line">
                {t('results.generateHint')}
              </p>
            </div>
          )}
        </div>

        {/* Export */}
        <div className="p-3 border-t border-white/[0.06] shrink-0 space-y-2">
          {errorMessage && (
            <p className="text-[11px] text-red-400 flex items-center gap-1.5">
              <AlertCircle className="w-3.5 h-3.5 shrink-0" />
              {errorMessage}
            </p>
          )}
          {isSaving && (
            <p className="text-[11px] text-white/35 flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 animate-spin" />
              {t('results.saving')}
            </p>
          )}
          <button
            onClick={() => setScreen('export')}
            disabled={transcriptSegments.length === 0}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold
              bg-primary text-white hover:bg-primary/90 disabled:opacity-40 btn-glow transition-all duration-200"
          >
            {t('results.export')}
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};

export default ResultsScreen;
