import { useAppState } from '@/context/AppContext';
import diaricatLogo from '@/assets/diaricat-logo.png';

const FloatingBrand = ({ hidden = false }: { hidden?: boolean }) => {
  const { setScreen } = useAppState();
  if (hidden) return null;

  return (
    <button
      className="floating-brand no-drag"
      onClick={() => setScreen('home')}
      title="Inicio"
    >
      <img
        src={diaricatLogo}
        alt="Diaricat"
        className="w-[24px] h-[24px] rounded-[6px] object-contain"
        draggable={false}
      />
      <span className="floating-brand-name">Diaricat</span>
    </button>
  );
};

export default FloatingBrand;
