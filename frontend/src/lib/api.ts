/** Thin client for the backend REST API (contract: docs/API.md, docs/openapi.json). */

export const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || '/api/v1';

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields: Record<string, string> = {},
    public retryAfter: number | null = null,
  ) {
    super(message);
  }
  get isNetwork(): boolean {
    return this.status === 0;
  }
}

async function parse(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const h = new Headers(headers);
  h.set('Accept', 'application/json');
  let body = rest.body;
  if (json !== undefined) {
    h.set('Content-Type', 'application/json');
    body = JSON.stringify(json);
  }
  let res: Response;
  try {
    res = await fetch(API_URL + path, { ...rest, headers: h, body });
  } catch {
    throw new ApiError(0, 'network', 'Нет связи с сервером');
  }
  const data = await parse(res);
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string; fields?: Record<string, string> } } | null)
      ?.error;
    const ra = res.headers.get('Retry-After');
    throw new ApiError(
      res.status,
      err?.code || `http_${res.status}`,
      err?.message || 'Ошибка сервера',
      err?.fields || {},
      ra ? Number(ra) : null,
    );
  }
  return data as T;
}

export function uuid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

// --- types (only what the UI reads) ---------------------------------------------------------------

export interface Messenger {
  title: string;
  url: string;
  is_placeholder?: boolean;
}

export interface PublicSettings {
  company: { name: string; legal_name: string; tagline?: string; city?: string; requisites?: Record<string, string> };
  contacts: { phone: string; phone_display: string; phone_href?: string; email: string; callback_promise_minutes?: number };
  messengers: Record<string, Messenger>;
  address: { text: string; lat: number; lon: number; map_zoom?: number };
  work_hours: { mode: string; note?: string };
  stats: { is_demo: boolean; items: { key: string; value: number; suffix: string; label: string }[] };
  warranty: { months: number; text: string };
  advantages: { title: string; text: string }[];
  review_links: { yandex?: string; '2gis'?: string; placeholders?: string[] };
  dispatch: { eta_minutes: number; radius_km: number; note?: string };
  consent: { version: string; text: string };
  work_status: { is_open: boolean; mode: string; label: string };
  telegram_bot: { username: string; url: string } | null;
  maps?: { provider: string; mapgl_key: string | null; style?: string | null };
}

export interface Service {
  slug: string;
  title: string;
  short_description: string;
  description: string;
  category: string;
  items: string[];
  icon: string;
  badge: string | null;
  is_24_7: boolean;
  form_type: string;
  prefill: { lead_type: string; service_slug: string; location_mode: string };
}

export interface Review {
  id: number;
  author: string;
  rating: number;
  text: string;
  date: string;
  source: string;
  source_label: string;
  vehicle_brand: string | null;
  case_id: number | null;
  has_case: boolean;
}

export interface ReviewSummary {
  average_rating: number;
  total: number;
  by_source: Record<string, { count: number; average: number; label: string }>;
  review_links: PublicSettings['review_links'];
}

export interface Bootstrap {
  settings: PublicSettings;
  services: Service[];
  reviews: { summary: ReviewSummary; top: Review[] };
  brands: { slug: string; title: string; origin: string }[];
  dispatch_zone: { center: { lat: number; lon: number }; radius_km: number; eta_minutes: number };
}

export interface CasePhoto {
  url: string;
  preview_url: string;
  caption?: string | null;
}

export interface CaseOut {
  id: number;
  title: string;
  vehicle: { brand: string; model?: string | null; year?: number | null };
  problem: string;
  work_done: string[];
  duration_hours: number | null;
  price_from: number | null;
  photos: { before: CasePhoto[]; after: CasePhoto[] };
}

export interface CalcOptions {
  brands: { slug: string; title: string; origin: string; origin_label: string }[];
  vehicle_types: { slug: string; title: string }[];
  work_types: { slug: string; title: string; is_onsite_service: boolean }[];
  surcharges: { urgent_pct: number; onsite_fee: number };
  disclaimer: string;
}

export interface Estimate {
  estimate_id: string;
  price_from: number;
  price_label: string;
  breakdown: { label: string; amount: number }[];
  input: { brand: string; vehicle_type: string | null; work_type: string; urgent: boolean; onsite: boolean };
  disclaimer: string;
  lead_prefill?: { estimate_id: string; lead_type: string };
}

export interface FormSchema {
  form_type: string;
  callback_eta_minutes: number;
  form_token: string;
}

export interface LeadCreated {
  id: string;
  number: string;
  public_token: string;
  tracking_url: string;
  status: string;
  status_label: string;
  summary: {
    type: string;
    type_label: string;
    name: string | null;
    phone_masked: string;
    vehicle_brand: string | null;
    vehicle_type: string | null;
    address: string | null;
    photos_count: number;
  };
  callback_eta_minutes: number;
  message: string;
  telegram_bind_url: string | null;
}

export interface OrderOut {
  number: string;
  status: string;
  status_label: string;
  is_cancelled: boolean;
  steps: { status: string; label: string; done: boolean; current: boolean }[];
  history: { status: string; label: string; at: string; comment: string | null }[];
  summary: LeadCreated['summary'] & {
    created_at: string;
    description: string | null;
    vehicle_type_label?: string | null;
    details: { label: string; value: string }[];
    photos: { preview_url: string; url: string }[];
    estimate: (Omit<Estimate, 'estimate_id' | 'disclaimer'> & { description?: string }) | null;
  };
  callback_eta_minutes: number;
  telegram_bind_url: string | null;
  telegram_bound: boolean;
  email_notifications: boolean;
  created_at: string;
  updated_at: string;
}

export interface GeoItem {
  name: string;
  full_name: string;
  address: string | null;
  lat: number;
  lon: number;
  type: string;
}

export interface ZoneCheck {
  zone: 'inside' | 'region' | 'outside';
  distance_km: number;
  eta_minutes: number | null;
  message: string;
}
