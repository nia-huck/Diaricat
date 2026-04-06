import { useAppState } from '@/context/AppContext';
import { Settings } from 'lucide-react';

const FloatingNav = ({ hidden = false }: { hidden?: boolean }) => {
  const { screen, setScreen, isBusy } = useAppState();
  // Hide during processing to prevent accidental pipeline interruption
  if (hidden || (isBusy && screen === 'processing')) return null;

  return (
    <div className="floating-nav no-drag">
      <button
        onClick={() => setScreen(screen === 'settings' ? 'home' : 'settings')}
        className={`floating-nav-btn transition-colors duration-150 ${
          screen === 'settings' ? 'text-primary' : ''
        }`}
        title="Configuracion"
      >
        <Settings className="w-4.5 h-4.5" />
      </button>
    </div>
  );
};

export default FloatingNav;
