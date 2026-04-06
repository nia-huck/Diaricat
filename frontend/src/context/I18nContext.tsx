import React, { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { type Lang, getStoredLang, storeLang, translate } from '@/lib/i18n';

interface I18nState {
  lang: Lang;
  setLang: (lang: Lang) => void;
  toggleLang: () => void;
  t: (key: string) => string;
}

const I18nContext = createContext<I18nState | null>(null);

export const useI18n = (): I18nState => {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used within I18nProvider');
  return ctx;
};

export const I18nProvider = ({ children }: { children: ReactNode }) => {
  const [lang, setLangState] = useState<Lang>(getStoredLang);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    storeLang(l);
  }, []);

  const toggleLang = useCallback(() => {
    setLangState((prev) => {
      const next = prev === 'es' ? 'en' : 'es';
      storeLang(next);
      return next;
    });
  }, []);

  const t = useCallback((key: string) => translate(key, lang), [lang]);

  const value = useMemo(() => ({ lang, setLang, toggleLang, t }), [lang, setLang, toggleLang, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};
