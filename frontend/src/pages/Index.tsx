import { AppProvider, useAppState } from '@/context/AppContext';
import { I18nProvider } from '@/context/I18nContext';
import FloatingNav from '@/components/FloatingNav';
import FloatingBrand from '@/components/FloatingBrand';
import LanguageToggle from '@/components/LanguageToggle';
import HomeScreen from '@/components/screens/HomeScreen';
import ProcessingScreen from '@/components/screens/ProcessingScreen';
import ResultsScreen from '@/components/screens/ResultsScreen';
import ExportScreen from '@/components/screens/ExportScreen';
import SettingsScreen from '@/components/screens/SettingsScreen';
import SetupWizard from '@/components/screens/SetupWizard';
import { useEffect, useRef, useState } from 'react';

export const STARTUP_HANDOFF_STORAGE_KEY = 'diaricat.startup.handoff.v1';

export const shouldShowStartupHandoff = (): boolean => {
  try {
    if (sessionStorage.getItem(STARTUP_HANDOFF_STORAGE_KEY) === '1') return false;
    sessionStorage.setItem(STARTUP_HANDOFF_STORAGE_KEY, '1');
    return true;
  } catch {
    return true;
  }
};

type Particle = {
  baseX: number; baseY: number;
  size: number; depth: number;
  driftRadius: number; driftSpeed: number;
  driftPhaseX: number; driftPhaseY: number;
  birth: number; lifespan: number; maxOpacity: number;
  flickerSpeed: number; flickerDepth: number; flickerPhase: number;
  hue: number; sat: number; light: number;
};

const AppContent = () => {
  const { screen } = useAppState();
  const isSetup = screen === 'setup';
  const [showHandoff, setShowHandoff] = useState(() => shouldShowStartupHandoff());
  const particlesRef = useRef<HTMLCanvasElement>(null);

  // Mouse-reactive specular on glass panels
  useEffect(() => {
    const update = (e: globalThis.MouseEvent) => {
      const pct = Math.max(0, Math.min(100, (e.clientX / Math.max(window.innerWidth, 1)) * 100));
      document.documentElement.style.setProperty('--lg-scroll', `${pct.toFixed(2)}%`);
    };
    window.addEventListener('mousemove', update, { passive: true });
    return () => window.removeEventListener('mousemove', update);
  }, []);

  // Startup handoff fade
  useEffect(() => {
    if (!showHandoff) return;
    const t = window.setTimeout(() => setShowHandoff(false), 1200);
    return () => window.clearTimeout(t);
  }, [showHandoff]);

  // Particle system — Grok-style living background
  useEffect(() => {
    const canvas = particlesRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let particles: Particle[] = [];
    let animId = 0;

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };

    const createParticle = (stagger: boolean): Particle => {
      const lifespan = 5000 + Math.random() * 10000;
      const depth = Math.random();
      const baseX = Math.random() * canvas.width;
      const baseY = Math.random() * canvas.height;
      return {
        baseX, baseY,
        size:
          depth < 0.3
            ? Math.random() * 0.6 + 0.3
            : depth < 0.7
              ? Math.random() * 1.2 + 0.5
              : Math.random() * 1.8 + 0.8,
        depth,
        driftRadius: Math.random() * 20 + 6,
        driftSpeed: Math.random() * 0.0003 + 0.00015,
        driftPhaseX: Math.random() * Math.PI * 2,
        driftPhaseY: Math.random() * Math.PI * 2,
        birth: performance.now() + (stagger ? Math.random() * 5000 : 0),
        lifespan,
        maxOpacity:
          depth < 0.3
            ? Math.random() * 0.2 + 0.08
            : depth < 0.7
              ? Math.random() * 0.4 + 0.15
              : Math.random() * 0.5 + 0.2,
        flickerSpeed: Math.random() * 0.002 + 0.0008,
        flickerDepth: Math.random() * 0.3 + 0.1,
        flickerPhase: Math.random() * Math.PI * 2,
        hue: Math.random() > 0.6 ? 268 : Math.random() > 0.4 ? 240 : 0,
        sat: Math.random() > 0.8 ? 0 : Math.random() * 25 + 45,
        light: Math.random() * 15 + 78,
      };
    };

    const respawn = (p: Particle) => {
      Object.assign(p, createParticle(false));
      p.birth = performance.now();
    };

    const init = () => {
      resize();
      const count = Math.min(Math.floor(canvas.width * canvas.height / 9000), 90);
      particles = Array.from({ length: count }, () => createParticle(true));
    };

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const now = performance.now();
      for (const p of particles) {
        const age = now - p.birth;
        if (age < 0) continue;
        const remaining = p.lifespan - age;
        if (remaining <= 0) { respawn(p); continue; }
        const envelope = Math.min(age / 1000, 1) * Math.min(remaining / 1500, 1);
        const flicker = 1 - p.flickerDepth * (0.5 + 0.5 * Math.sin(now * p.flickerSpeed + p.flickerPhase));
        const alpha = p.maxOpacity * envelope * flicker;
        if (alpha < 0.01) continue;
        const x = p.baseX + Math.sin(now * p.driftSpeed + p.driftPhaseX) * p.driftRadius;
        const y = p.baseY + Math.cos(now * p.driftSpeed * 0.8 + p.driftPhaseY) * p.driftRadius;
        ctx.beginPath();
        ctx.arc(x, y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = `hsla(${p.hue},${p.sat}%,${p.light}%,${alpha})`;
        ctx.fill();
        if (p.depth > 0.6 && alpha > 0.12) {
          ctx.beginPath();
          ctx.arc(x, y, p.size * 3.5, 0, Math.PI * 2);
          ctx.fillStyle = `hsla(${p.hue},${p.sat}%,${p.light}%,${alpha * 0.06})`;
          ctx.fill();
        }
      }
      animId = requestAnimationFrame(draw);
    };

    // On resize: scale existing particle positions proportionally — no restart
    const onResize = () => {
      const oldW = canvas.width || 1;
      const oldH = canvas.height || 1;
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      if (particles.length > 0) {
        const sx = canvas.width / oldW;
        const sy = canvas.height / oldH;
        for (const p of particles) { p.baseX *= sx; p.baseY *= sy; }
      }
    };
    window.addEventListener('resize', onResize);

    const timeoutId = window.setTimeout(() => {
      init();
      draw();
      canvas.classList.add('active');
    }, 2500);

    return () => {
      window.clearTimeout(timeoutId);
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', onResize);
    };
  }, []);

  return (
    <div className="relative h-screen w-screen overflow-hidden" style={{ background: '#000' }}>

      {/* ── Background layer ── */}
      <div className="app-starfield" aria-hidden="true" />
      <div className="psg-orb psg-orb-1" aria-hidden="true" />
      <div className="psg-orb psg-orb-2" aria-hidden="true" />
      <div className="psg-orb psg-orb-3" aria-hidden="true" />
      <canvas ref={particlesRef} className="particles-canvas" aria-hidden="true" />

      {/* ── Edge vignette — fades particles into native title bar + corners ── */}
      <div className="edge-vignette" aria-hidden="true" />

      {/* ── Main content ── */}
      <div className="screen-shell window-shell relative z-[4] h-full w-full">
        {showHandoff && (
          <div className="app-handoff" data-testid="startup-handoff">
            <div className="spark-layer" />
          </div>
        )}

        <div className="relative h-full flex flex-col overflow-hidden">
          {isSetup && <SetupWizard />}
          {!isSetup && screen === 'home'       && <HomeScreen />}
          {!isSetup && screen === 'processing' && <ProcessingScreen />}
          {!isSetup && screen === 'results'    && <ResultsScreen />}
          {!isSetup && screen === 'export'     && <ExportScreen />}
          {!isSetup && screen === 'settings'   && <SettingsScreen />}
        </div>
      </div>

      {/* ── Floating nav pill ── */}
      <FloatingNav hidden={isSetup} />
      <LanguageToggle hidden={isSetup} />
      <FloatingBrand hidden={isSetup} />
    </div>
  );
};

const Index = () => (
  <I18nProvider>
    <AppProvider>
      <AppContent />
    </AppProvider>
  </I18nProvider>
);

export default Index;
