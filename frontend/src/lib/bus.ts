/** Cross-component intents (same events as the prototype: open the chat, jump to the form). */

export type UiFormType = 'sto' | 'visit' | 'evac' | 'parts' | 'corp' | 'callback';

export interface MapPoint {
  lat: number;
  lon: number;
  addr: string; // human-readable; empty when reverse geocoding found nothing
  km: number;
  zone: 'inside' | 'region' | 'outside';
  mins: number | null;
  message: string;
}

export interface CalcAttachment {
  estimateId: string;
  total: string;
  desc: string;
  onsite: boolean;
}

export interface FormIntent {
  type?: UiFormType;
  problem?: string;
  serviceSlug?: string;
  point?: MapPoint;
  calc?: CalcAttachment;
}

export const FORM_EVENT = 'gs:form';
export const CHAT_EVENT = 'gs:open-chat';

/** Set by the home page while it is mounted, so other pages know to navigate first. */
export const homeState = { mounted: false, pending: null as FormIntent | null };

export function openForm(intent: FormIntent, navigate?: (to: string) => void): void {
  if (homeState.mounted) {
    window.dispatchEvent(new CustomEvent<FormIntent>(FORM_EVENT, { detail: intent }));
  } else {
    homeState.pending = intent;
    if (navigate) navigate('/#form');
    else window.location.href = '/#form';
  }
}

export function openChat(): void {
  window.dispatchEvent(new CustomEvent(CHAT_EVENT));
}

export function scrollToId(id: string, navigate?: (to: string) => void): void {
  const el = document.getElementById(id);
  if (el) {
    window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 70, behavior: 'smooth' });
  } else if (navigate) {
    navigate('/#' + id);
  }
}

/** UI form tabs ↔ backend lead types. */
export const LEAD_TYPE: Record<UiFormType, string> = {
  sto: 'repair',
  visit: 'onsite',
  evac: 'tow',
  parts: 'parts',
  corp: 'corporate',
  callback: 'callback',
};

export function uiType(leadType: string): UiFormType {
  const hit = (Object.keys(LEAD_TYPE) as UiFormType[]).find((k) => LEAD_TYPE[k] === leadType);
  return hit || 'sto';
}
