import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, type Bootstrap, type PublicSettings } from './lib/api';

interface SiteState {
  data: Bootstrap | null;
  error: boolean;
  reload: () => void;
}

const Ctx = createContext<SiteState>({ data: null, error: false, reload: () => {} });

export function SiteProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [error, setError] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setError(false);
    api<Bootstrap>('/bootstrap')
      .then((d) => alive && setData(d))
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, [tick]);
  return <Ctx.Provider value={{ data, error, reload: () => setTick((t) => t + 1) }}>{children}</Ctx.Provider>;
}

export function useSite(): SiteState {
  return useContext(Ctx);
}

/** Contacts with safe fallbacks while /bootstrap is loading (the phone must always work). */
export function useContacts() {
  const s: PublicSettings | undefined = useSite().data?.settings;
  const phone = s?.contacts.phone || '';
  const tg = s?.messengers.telegram;
  const max = s?.messengers.max;
  return {
    phoneHref: phone ? `tel:${phone}` : undefined,
    phoneDisplay: s?.contacts.phone_display || '',
    email: s?.contacts.email || '',
    address: s?.address.text || '',
    hours: s?.work_hours.note || 'Круглосуточно, без выходных',
    statusLabel: s?.work_status.is_open === false ? 'Сейчас закрыто' : 'Работаем круглосуточно',
    isOpen: s?.work_status.is_open !== false,
    tgUrl: tg && !tg.is_placeholder ? tg.url : s?.telegram_bot?.url,
    maxUrl: max && !max.is_placeholder ? max.url : undefined,
    botUrl: s?.telegram_bot?.url,
    legalName: s?.company.legal_name || 'ООО «ГРУЗСПЕЦСЕРВИС»',
    requisites: s?.company.requisites || {},
  };
}

export function useWidth(): number {
  const [w, setW] = useState(() => (typeof window === 'undefined' ? 1440 : window.innerWidth));
  useEffect(() => {
    const on = () => setW(window.innerWidth);
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  return w;
}
