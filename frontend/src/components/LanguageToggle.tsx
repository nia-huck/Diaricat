import { useI18n } from '@/context/I18nContext';
import { useAppState } from '@/context/AppContext';
import { Globe } from 'lucide-react';

const LanguageToggle = ({ hidden = false }: { hidden?: boolean }) => {
  const { lang, toggleLang } = useI18n();
  const { isBusy, screen } = useAppState();
  if (hidden || (isBusy && screen === 'processing')) return null;

  return (
    <button
      onClick={toggleLang}
      className="floating-lang no-drag"
      title={lang === 'es' ? 'Switch to English' : 'Cambiar a Espanol'}
    >
      <Globe className="w-3.5 h-3.5" />
      <span className="floating-lang-label">{lang.toUpperCase()}</span>
    </button>
  );
};

export default LanguageToggle;
