import { useAppState } from '@/context/AppContext';
import { useI18n } from '@/context/I18nContext';
import { HelpCircle, Settings } from 'lucide-react';
import diaricatLogo from '@/assets/diaricat-logo.png';
import type { AppScreen } from '@/context/AppContext';
import { useEffect, useMemo, useState, type MouseEvent } from 'react';

type WindowState = 'normal' | 'maximized' | 'minimized' | 'fullscreen' | 'unknown';

type DesktopApi = {
  minimize: () => Promise<void>;
  toggle_maximize: () => Promise<void>;
  toggle_fullscreen: () => Promise<void>;
  close_window: () => Promise<void>;
  start_window_drag: () => Promise<boolean>;
  start_window_resize: (edge: string) => Promise<boolean>;
  get_window_state: () => Promise<{ state: WindowState }>;
};

declare global {
  interface Window {
    pywebview?: { api: DesktopApi };
  }
}

const screenLabelKeys: Record<AppScreen, string> = {
  home: 'screen.home',
  processing: 'screen.processing',
  results: 'screen.results',
  export: 'screen.export',
  settings: 'screen.settings',
  setup: 'screen.setup',
};

const callApi = async <T,>(invoke: (api: DesktopApi) => Promise<T>): Promise<T | null> => {
  try {
    if (!window.pywebview?.api) return null;
    return await invoke(window.pywebview.api);
  } catch {
    return null;
  }
};

const TopBar = ({ hideActions = false }: { hideActions?: boolean }) => {
  const { screen, isBusy, settings, setScreen } = useAppState();
  const { t } = useI18n();
  const [isDesktop, setIsDesktop] = useState(() => Boolean(window.pywebview?.api));
  const [windowState, setWindowState] = useState<WindowState>('normal');

  useEffect(() => {
    const sync = () => setIsDesktop(Boolean(window.pywebview?.api));
    sync();
    window.addEventListener('pywebviewready', sync);
    const timer = window.setInterval(sync, 1000);
    return () => { window.removeEventListener('pywebviewready', sync); window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!isDesktop) return;
    let mounted = true;
    const poll = async () => {
      const state = await callApi((api) => api.get_window_state());
      if (!mounted || !state?.state) return;
      setWindowState(state.state);
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 900);
    return () => { mounted = false; window.clearInterval(timer); };
  }, [isDesktop]);

  const onExpand = () => {
    if (!isDesktop) return;
    if (settings?.fullscreen_on_maximize) {
      void callApi((api) => api.toggle_fullscreen());
    } else {
      void callApi((api) => api.toggle_maximize());
    }
  };

  const isMaximized = useMemo(
    () => windowState === 'maximized' && !(settings?.fullscreen_on_maximize ?? false),
    [settings?.fullscreen_on_maximize, windowState]
  );

  const blockDrag = (event: MouseEvent<HTMLElement>) => event.stopPropagation();

  const onTitleMouseDown = (event: MouseEvent<HTMLElement>) => {
    if (!isDesktop || event.button !== 0) return;
    const target = event.target as HTMLElement | null;
    if (target?.closest('.no-drag')) return;
    void callApi((api) => api.start_window_drag());
  };

  return (
    <header
      className="relative pywebview-drag-region h-10 flex items-stretch shrink-0 select-none topbar-glass"
      onMouseDown={onTitleMouseDown}
      onDoubleClick={onExpand}
      title={t('nav.drag')}
    >
      {/* Brand */}
      <div className="flex items-center gap-3 px-4">
        <button
          onClick={() => setScreen('home')}
          onMouseDown={blockDrag}
          onDoubleClick={blockDrag}
          className="no-drag flex items-center gap-2 hover:opacity-90 transition-opacity"
          title={t('nav.home')}
        >
          <img
            src={diaricatLogo}
            alt="Diaricat"
            className="w-5 h-5 rounded-md object-contain"
            draggable={false}
          />
          <span className="font-display font-semibold text-sm tracking-tight text-foreground/95">Diaricat</span>
        </button>

        <div className="w-px h-3.5 bg-white/8" />

        <div className="flex items-center gap-1.5">
          {isBusy && screen === 'processing' && (
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse shadow-[0_0_6px_hsl(var(--primary)/0.6)]" />
          )}
          <span className="font-mono text-[10px] tracking-widest uppercase text-muted-foreground/55">
            {t(screenLabelKeys[screen])}
          </span>
        </div>
      </div>

      <div className="flex-1" />

      {/* Actions — hidden during active processing to prevent interruption */}
      {!hideActions && !(isBusy && screen === 'processing') && (
        <div className="no-drag flex items-center gap-1 px-2" onMouseDown={blockDrag} onDoubleClick={blockDrag}>
          <button
            disabled
            title={t('nav.help')}
            className="h-7 w-7 rounded-lg glass-control flex items-center justify-center text-muted-foreground/50 disabled:opacity-25 disabled:cursor-not-allowed transition-all duration-150"
          >
            <HelpCircle className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => setScreen(screen === 'settings' ? 'home' : 'settings')}
            onMouseDown={blockDrag}
            onDoubleClick={blockDrag}
            title={t('nav.settings')}
            className={`h-7 w-7 rounded-lg glass-control flex items-center justify-center transition-all duration-200 ${
              screen === 'settings'
                ? 'text-primary shadow-[0_0_14px_hsl(var(--primary)/0.3)]'
                : 'text-muted-foreground/65 hover:text-foreground'
            }`}
          >
            <Settings className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

    </header>
  );
};

export default TopBar;
