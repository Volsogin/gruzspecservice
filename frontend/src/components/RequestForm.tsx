import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError, uuid, type FormSchema, type LeadCreated } from '../lib/api';
import { FORM_EVENT, homeState, LEAD_TYPE, type CalcAttachment, type FormIntent, type MapPoint, type UiFormType } from '../lib/bus';
import { s, sx } from '../lib/css';
import { fmtPhone, phoneDigits } from '../lib/format';
import { useContacts, useWidth } from '../site';
import { MapZone } from './MapZone';

export interface Submitted {
  lead: LeadCreated;
  email: string;
  calc: string;
}

type Opt = { value: string; label: string };
type Value = string | string[] | MapPoint | undefined;

interface FieldDef {
  wire: string;
  label: string;
  ph?: string;
  req?: boolean;
  type?: string;
  mode?: 'text' | 'tel' | 'email' | 'numeric';
  ac?: string;
  chips?: Opt[];
  multi?: boolean;
  area?: boolean;
  map?: boolean;
  always?: boolean;
  cond?: (v: Record<string, Value>) => boolean;
  max?: number;
}

const TYPES: [UiFormType, string][] = [
  ['sto', 'Ремонт на СТО'],
  ['visit', 'Выезд мастера'],
  ['evac', 'Эвакуатор'],
  ['parts', 'Запчасти'],
  ['corp', 'Корпоративное'],
  ['callback', 'Перезвоните мне'],
];

const VT: Opt[] = [
  { value: 'tractor', label: 'Тягач' },
  { value: 'dump', label: 'Самосвал' },
  { value: 'semitrailer', label: 'Полуприцеп' },
  { value: 'truck', label: 'Бортовой / фургон' },
  { value: 'special', label: 'Спецтехника' },
];

const SCHEMA: Record<UiFormType, string[]> = {
  sto: ['name', 'phone', 'brand', 'vtype', 'problem', 'when'],
  visit: ['point', 'addr', 'brand', 'vtype', 'moving', 'problem', 'name', 'phone'],
  evac: ['point', 'addr', 'dest', 'destAddr', 'moving', 'vtype', 'dims', 'name', 'phone'],
  parts: ['brand', 'part', 'vin', 'urgency', 'delivery', 'delAddr', 'name', 'phone'],
  corp: ['company', 'inn', 'fleet', 'vtypes', 'contact', 'phone', 'emailReq', 'comment'],
  callback: ['name', 'phone'],
};

const F: Record<string, FieldDef> = {
  name: { wire: 'name', label: 'Имя', ph: 'Имя', req: true, ac: 'given-name', max: 120 },
  contact: { wire: 'name', label: 'Контактное лицо', ph: 'Контактное лицо', req: true, ac: 'name', max: 120 },
  phone: { wire: 'phone', label: 'Телефон', ph: '+7 (___) ___-__-__', req: true, type: 'tel', mode: 'tel', ac: 'tel' },
  brand: { wire: 'vehicle_brand', label: 'Марка ТС', ph: 'Марка ТС', req: true, max: 64 },
  vtype: { wire: 'vehicle_type', label: 'Тип техники', req: true, chips: VT },
  vtypes: { wire: 'fleet_types', label: 'Типы техники в парке', req: true, chips: VT, multi: true },
  problem: { wire: 'description', label: 'Что случилось', ph: 'Что случилось', req: true, area: true, max: 2000 },
  when: { wire: 'preferred_at', label: 'Желаемые дата и время (необязательно)', type: 'datetime-local', always: true },
  point: { wire: 'location', label: 'Где машина', req: true, map: true },
  addr: { wire: 'address', label: 'Адрес или ориентир', ph: 'Адрес или ориентир', max: 300 },
  moving: { wire: 'is_drivable', label: 'Машина на ходу?', req: true, chips: [{ value: 'yes', label: 'Да' }, { value: 'no', label: 'Нет' }, { value: 'unknown', label: 'Не знаю' }] },
  dest: { wire: 'destination', label: 'Куда везти', req: true, chips: [{ value: 'our_sto', label: 'К вам на СТО' }, { value: 'other_address', label: 'Другой адрес' }] },
  destAddr: { wire: 'destination_address', label: 'Адрес доставки машины', ph: 'Куда везти — адрес', req: true, cond: (v) => v.dest === 'other_address', max: 300 },
  dims: { wire: 'dimensions', label: 'Габариты / масса', ph: 'Габариты / масса, напр. 12 м, 18 т', max: 200 },
  part: { wire: 'description', label: 'Какая деталь', ph: 'Какая деталь', req: true, max: 2000 },
  vin: { wire: 'vin', label: 'VIN', ph: 'VIN (необязательно)', max: 17 },
  urgency: { wire: 'urgency', label: 'Срочность', req: true, chips: [{ value: 'today', label: 'Сегодня' }, { value: 'this_week', label: 'На этой неделе' }, { value: 'not_urgent', label: 'Не срочно' }] },
  delivery: { wire: 'delivery', label: 'Получение', req: true, chips: [{ value: 'pickup', label: 'Самовывоз' }, { value: 'delivery', label: 'Доставка' }] },
  delAddr: { wire: 'delivery_address', label: 'Адрес доставки', ph: 'Адрес доставки', req: true, cond: (v) => v.delivery === 'delivery', max: 300 },
  company: { wire: 'company_name', label: 'Компания', ph: 'Компания', req: true, ac: 'organization', max: 200 },
  inn: { wire: 'inn', label: 'ИНН', ph: 'ИНН (необязательно)', mode: 'numeric', max: 12 },
  fleet: { wire: 'fleet_size', label: 'Сколько единиц в парке', req: true, chips: [{ value: '1-5', label: '1–5' }, { value: '6-20', label: '6–20' }, { value: '21-50', label: '21–50' }, { value: '50+', label: 'Больше 50' }] },
  emailReq: { wire: 'email', label: 'E-mail', ph: 'E-mail', req: true, type: 'email', mode: 'email', ac: 'email', max: 254 },
  comment: { wire: 'description', label: 'Комментарий', ph: 'Комментарий', area: true, max: 2000 },
};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const TG_RE = /^@?[A-Za-z0-9_]{5,32}$/;
const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'];
const MAX_PHOTO = 5 * 1024 * 1024;

type Status = 'idle' | 'sending' | 'network' | 'ratelimit' | 'error';

interface Photo {
  file: File;
  url: string;
}

function lineColor(err: boolean) {
  return { borderBottomColor: err ? 'rgb(255,107,107)' : 'rgb(204,21,23)', borderBottomWidth: err ? '2px' : '1px' };
}

interface Props {
  mode: 'main' | 'corp';
  onSubmitted: (r: Submitted) => void;
}

export function RequestForm({ mode, onSubmitted }: Props) {
  const m = useWidth() < 860;
  const c = useContacts();
  const [type, setType] = useState<UiFormType>(mode === 'corp' ? 'corp' : 'sto');
  const [v, setV] = useState<Record<string, Value>>({});
  const [email, setEmail] = useState('');
  const [tg, setTg] = useState('');
  const [consent, setConsent] = useState(false);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [photoErr, setPhotoErr] = useState('');
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [tried, setTried] = useState(false);
  const [status, setStatus] = useState<Status>('idle');
  const [serverMsg, setServerMsg] = useState('');
  const [picker, setPicker] = useState(false);
  const [calc, setCalc] = useState<CalcAttachment | null>(null);
  const [serviceSlug, setServiceSlug] = useState<string | null>(null);
  const [flash, setFlash] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const honeypot = useRef<HTMLInputElement>(null);
  const tokens = useRef<Record<string, Promise<string>>>({});
  const idem = useRef<string | null>(null);

  const formToken = (t: UiFormType, fresh = false): Promise<string> => {
    const lt = LEAD_TYPE[t];
    if (fresh || !tokens.current[lt]) {
      tokens.current[lt] = api<FormSchema>(`/forms/${lt}`)
        .then((f) => f.form_token)
        .catch(() => {
          delete tokens.current[lt];
          return '';
        });
    }
    return tokens.current[lt];
  };

  useEffect(() => {
    void formToken(type);
  }, [type]); // eslint-disable-line react-hooks/exhaustive-deps

  const applyIntent = (det: FormIntent) => {
    setV((prev) => {
      const next = { ...prev };
      if (det.problem && !next.problem) next.problem = det.problem;
      if (det.point) {
        next.point = det.point;
        if (det.point.addr) next.addr = det.point.addr;
      }
      return next;
    });
    if (det.type) setType(det.type);
    if (det.calc !== undefined) setCalc(det.calc);
    setServiceSlug(det.serviceSlug || null);
    setErrs({});
    setTried(false);
    setStatus('idle');
    setFlash(true);
    setTimeout(() => setFlash(false), 1200);
    requestAnimationFrame(() => {
      const el = rootRef.current;
      if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 84, behavior: 'smooth' });
    });
  };

  useEffect(() => {
    if (mode === 'corp') return;
    const on = (e: Event) => applyIntent((e as CustomEvent<FormIntent>).detail || {});
    window.addEventListener(FORM_EVENT, on);
    if (homeState.pending) {
      const p = homeState.pending;
      homeState.pending = null;
      setTimeout(() => applyIntent(p), 300);
    }
    return () => window.removeEventListener(FORM_EVENT, on);
  }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => photos.forEach((p) => URL.revokeObjectURL(p.url)), []); // eslint-disable-line react-hooks/exhaustive-deps

  const keys = SCHEMA[type].filter((k) => !F[k].cond || F[k].cond!(v));

  const validate = (vals = v, em = email, t = tg, ok = consent): Record<string, string> => {
    const e: Record<string, string> = {};
    for (const k of SCHEMA[type].filter((key) => !F[key].cond || F[key].cond!(vals))) {
      const f = F[k];
      const val = vals[k];
      const empty = val == null || val === '' || (Array.isArray(val) && !val.length);
      if (f.req && empty) e[k] = k === 'point' ? 'Отметьте точку на карте' : f.chips ? 'Выберите вариант' : 'Заполните поле';
      else if (k === 'phone' && phoneDigits(String(val)).length < 11) e[k] = 'Номер неполный — нужно 10 цифр после +7';
      else if (k === 'emailReq' && !EMAIL_RE.test(String(val))) e[k] = 'Проверьте e-mail';
      else if (k === 'inn' && val && !/^\d{10}(\d{2})?$/.test(String(val))) e[k] = 'ИНН — 10 или 12 цифр';
      else if (k === 'vin' && val && !/^[A-HJ-NPR-Z0-9]{17}$/i.test(String(val))) e[k] = 'VIN — 17 символов, без I, O, Q';
    }
    if (em && type !== 'corp' && !EMAIL_RE.test(em)) e.email = 'Проверьте e-mail';
    if (t && !TG_RE.test(t)) e.tg = 'Ник — латиница, цифры и _, от 5 символов';
    if (!ok) e.consent = 'Нужно согласие, чтобы отправить заявку';
    return e;
  };

  const revalidate = (vals = v, em = email, t = tg, ok = consent) => {
    if (tried) setErrs(validate(vals, em, t, ok));
  };

  const setVal = (k: string, val: Value) => {
    const next = { ...v, [k]: val };
    setV(next);
    idem.current = null;
    if (status === 'network' || status === 'error') setStatus('idle');
    revalidate(next);
  };

  const buildBody = (token: string): FormData => {
    const fd = new FormData();
    fd.append('lead_type', LEAD_TYPE[type]);
    for (const k of keys) {
      const f = F[k];
      const val = v[k];
      if (val == null || val === '' || (Array.isArray(val) && !val.length)) continue;
      if (f.map) {
        const p = val as MapPoint;
        fd.append('lat', String(p.lat));
        fd.append('lon', String(p.lon));
      } else if (Array.isArray(val)) {
        val.forEach((x) => fd.append(f.wire, x));
      } else {
        fd.append(f.wire, String(val).trim());
      }
    }
    if ((type === 'visit' || type === 'evac') && !v.addr && (v.point as MapPoint | undefined)?.addr) {
      fd.append('address', (v.point as MapPoint).addr);
    }
    if (email && type !== 'corp') fd.append('email', email.trim());
    if (tg) fd.append('telegram_username', tg.trim());
    fd.append('consent', 'true');
    fd.append('source', calc ? 'calculator' : 'form');
    if (calc) fd.append('estimate_id', calc.estimateId);
    if (serviceSlug) fd.append('service_slug', serviceSlug);
    if (token) fd.append('form_token', token);
    fd.append('website', honeypot.current?.value || '');
    if (type !== 'callback') photos.forEach((p) => fd.append('photos', p.file, p.file.name));
    return fd;
  };

  const mapServerErrors = (fields: Record<string, string>): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const [wire, msg] of Object.entries(fields)) {
      if (wire === 'lat' || wire === 'lon' || wire === 'location') out.point = msg;
      else if (wire === 'telegram_username') out.tg = msg;
      else if (wire === 'consent') out.consent = msg;
      else if (wire === 'photos') setPhotoErr(msg);
      else if (wire === 'email' && type !== 'corp') out.email = msg;
      else {
        const k = keys.find((key) => F[key].wire === wire) || (wire === 'address' ? 'addr' : null);
        if (k) out[k] = msg;
      }
    }
    return out;
  };

  const submit = async (attempt = 0): Promise<void> => {
    setTried(true);
    const e = validate();
    setErrs(e);
    if (Object.keys(e).length) {
      requestAnimationFrame(() => rootRef.current?.querySelector('[data-err="1"]')?.scrollIntoView({ block: 'center', behavior: 'smooth' }));
      return;
    }
    setStatus('sending');
    setServerMsg('');
    if (!idem.current) idem.current = uuid();
    try {
      const token = await formToken(type, attempt > 0);
      const lead = await api<LeadCreated>('/leads', { method: 'POST', body: buildBody(token), headers: { 'Idempotency-Key': idem.current } });
      idem.current = null;
      setStatus('idle');
      onSubmitted({ lead, email: type === 'corp' ? String(v.emailReq || '') : email, calc: calc?.total || '' });
      photos.forEach((p) => URL.revokeObjectURL(p.url));
      setV({});
      setPhotos([]);
      setCalc(null);
      setServiceSlug(null);
      setTried(false);
      setErrs({});
      void formToken(type, true);
    } catch (err) {
      const ae = err instanceof ApiError ? err : new ApiError(0, 'network', '');
      if (ae.isNetwork || ae.status >= 500) return setStatus('network');
      if (ae.status === 429) return setStatus('ratelimit');
      if (attempt === 0 && (ae.code.startsWith('form_token') || ae.code === 'idempotency_conflict')) {
        idem.current = null;
        return submit(1);
      }
      if (ae.status === 422 && Object.keys(ae.fields).length) {
        setStatus('idle');
        setErrs(mapServerErrors(ae.fields));
        return;
      }
      setServerMsg(ae.message || 'Не удалось отправить заявку');
      setStatus('error');
    }
  };

  const onFiles = (list: FileList | null) => {
    const files = Array.from(list || []);
    const room = 5 - photos.length;
    const ok: Photo[] = [];
    let err = '';
    for (const f of files) {
      if (ok.length >= room) {
        err = 'Можно прикрепить не больше 5 фото';
        break;
      }
      if (f.type && !PHOTO_TYPES.includes(f.type)) {
        err = 'Подходят фото JPG, PNG, WebP или HEIC';
        continue;
      }
      if (f.size > MAX_PHOTO) {
        err = `«${f.name}» больше 5 МБ`;
        continue;
      }
      ok.push({ file: f, url: URL.createObjectURL(f) });
    }
    setPhotoErr(err);
    setPhotos((p) => [...p, ...ok]);
    idem.current = null;
  };

  const busy = status === 'sending';
  const n = photos.length;
  const field = (k: string): ReactNode => {
    const f = F[k];
    const val = v[k];
    const err = errs[k];
    const has = !!err;
    const showLabel = !!f.chips || !!f.always || (!f.map && !!val && !f.chips);
    let control: ReactNode;
    if (f.chips) {
      control = (
        <div style={s('display:flex;flex-wrap:wrap;gap:8px;justify-content:center')} role="group" aria-label={f.label}>
          {f.chips.map((o) => {
            const act = f.multi ? ((val as string[] | undefined) || []).includes(o.value) : val === o.value;
            return (
              <button
                key={o.value}
                type="button"
                aria-pressed={act}
                disabled={busy}
                onClick={() => {
                  const cur = (val as string[] | undefined) || [];
                  setVal(k, f.multi ? (act ? cur.filter((x) => x !== o.value) : [...cur, o.value]) : o.value);
                }}
                style={sx('min-height:44px;padding:0 16px;border-radius:999px;border:1px solid;color:#fff;font-family:K2D,Jost,sans-serif;font-weight:300;font-size:16px;cursor:pointer', {
                  background: act ? 'rgb(204,21,23)' : 'transparent',
                  borderColor: act ? 'rgb(204,21,23)' : has ? 'rgba(255,107,107,0.6)' : 'rgba(255,255,255,0.22)',
                })}
              >
                {o.label}
              </button>
            );
          })}
        </div>
      );
    } else if (f.map) {
      const p = val as MapPoint | undefined;
      const dot = p?.zone === 'inside' ? 'oklch(0.72 0.17 150)' : p?.zone === 'outside' ? 'oklch(0.82 0.16 85)' : 'rgb(184,184,184)';
      const km = p ? String(p.km).replace('.', ',') : '';
      const zoneText = !p ? '' : p.zone === 'inside' ? `${km} км от СТО · приедем примерно за ${p.mins ?? 30} мин` : p.zone === 'outside' ? `${km} км — вне зоны, диспетчер перезвонит и подскажет` : `${km} км от СТО · время уточнит диспетчер`;
      control = (
        <>
          <button type="button" disabled={busy} onClick={() => setPicker(true)} style={sx("width:100%;min-height:56px;display:flex;align-items:center;justify-content:center;gap:12px;background:transparent;border:0;border-bottom-style:solid;color:#fff;font-family:K2D,Jost,sans-serif;font-weight:300;font-size:22px;cursor:pointer;padding:8px 4px 12px", lineColor(has))}>
            <span style={s('width:20px;height:26px;flex:none;background:url(/assets/icon-b.webp) center / contain no-repeat;filter:invert(1)')} />
            {p ? 'Точка выбрана · изменить' : 'Указать точку на карте'}
          </button>
          {p && (
            <span style={s('display:flex;align-items:center;gap:8px;font-size:15px;color:rgb(184,184,184);text-align:center')}>
              <span style={sx('width:8px;height:8px;border-radius:50%;flex:none', { background: dot })} />
              {zoneText}
            </span>
          )}
        </>
      );
    } else if (f.area) {
      control = (
        <textarea rows={2} value={(val as string) || ''} maxLength={f.max} onChange={(e) => setVal(k, e.target.value)} placeholder={f.ph} aria-label={f.label} aria-invalid={has} disabled={busy} className="fc-white" style={sx('width:100%;box-sizing:border-box;background:transparent;border:0;border-bottom-style:solid;padding:8px 4px 12px;color:#fff;font-family:K2D,Jost,sans-serif;font-weight:300;font-size:22px;text-align:center;outline:none;resize:vertical;border-radius:0', lineColor(has))} />
      );
    } else {
      control = (
        <input
          type={f.type || 'text'}
          inputMode={f.mode || 'text'}
          autoComplete={f.ac || 'off'}
          maxLength={f.type === 'tel' ? 18 : f.max}
          value={(val as string) || ''}
          onChange={(e) => setVal(k, k === 'phone' ? fmtPhone(e.target.value) : k === 'vin' ? e.target.value.toUpperCase() : e.target.value)}
          placeholder={f.ph}
          aria-label={f.label}
          aria-invalid={has}
          disabled={busy}
          className="fc-white"
          style={sx('width:100%;box-sizing:border-box;background:transparent;border:0;border-bottom-style:solid;padding:8px 4px 12px;color:#fff;font-family:K2D,Jost,sans-serif;font-weight:300;font-size:22px;text-align:center;outline:none;color-scheme:dark;border-radius:0', lineColor(has))}
        />
      );
    }
    return (
      <div key={k} data-err={has ? '1' : undefined} style={s('display:flex;flex-direction:column;align-items:center;gap:8px;width:100%')}>
        {showLabel && <span style={s('font-size:14px;color:rgb(184,184,184);text-align:center')}>{f.label}</span>}
        {control}
        {has && <span style={s('font-size:14px;color:rgb(255,107,107);text-align:center')}>{err}</span>}
      </div>
    );
  };

  const eLine = (k: string) => (errs[k] ? 'rgb(255,107,107)' : 'rgba(255,255,255,0.2)');

  return (
    <div ref={rootRef} style={sx('position:relative;background:rgb(30,30,30);border-radius:23px;padding:clamp(24px,3vw,40px) clamp(16px,3vw,40px);display:flex;flex-direction:column;align-items:center;gap:28px;font-family:K2D,Jost,sans-serif;color:#fff;transition:box-shadow .4s', { boxShadow: flash ? '0 0 0 2px rgb(204,21,23), 0 0 48px rgba(204,21,23,0.35)' : '0 0 0 0 transparent' })}>
      <div style={s('display:flex;flex-direction:column;align-items:center;gap:0')}>
        <h2 style={s('margin:0;font-family:K2D,Jost,sans-serif;font-weight:200;font-size:32px;line-height:1;padding:0 40px 14px;border-bottom:1px solid rgb(204,21,23)')}>{mode === 'corp' ? 'Заявка для юрлиц' : 'Заявка'}</h2>
      </div>
      {mode !== 'corp' && (
        <div role="tablist" aria-label="Тип заявки" style={s('width:100%;display:flex;gap:6px;overflow-x:auto;justify-content:safe center;padding-bottom:4px;scrollbar-width:none')}>
          {TYPES.map(([id, label]) => (
            <button
              key={id}
              role="tab"
              aria-selected={id === type}
              onClick={() => {
                setType(id);
                setErrs({});
                setTried(false);
                setStatus('idle');
                idem.current = null;
              }}
              className="hv-bd-accent"
              style={sx("flex:none;height:44px;padding:0 18px;border-radius:999px;border:1px solid;color:#fff;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:18px;cursor:pointer;white-space:nowrap", {
                background: id === type ? 'rgb(204,21,23)' : 'transparent',
                borderColor: id === type ? 'rgb(204,21,23)' : 'rgba(255,255,255,0.22)',
              })}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      {calc && (
        <div style={s('width:100%;max-width:560px;box-sizing:border-box;display:flex;align-items:center;gap:12px;padding:12px 14px 12px 18px;border-radius:13px;background:rgba(204,21,23,0.16);border:1px solid rgba(204,21,23,0.5)')}>
          <div style={s('flex:1;display:flex;flex-direction:column;gap:2px')}>
            <span style={s('font-size:13px;color:rgb(184,184,184)')}>Расчёт калькулятора</span>
            <span style={s('font-size:17px')}>{`${calc.total} · ${calc.desc}`}</span>
          </div>
          <button onClick={() => setCalc(null)} aria-label="Убрать расчёт" style={s('width:36px;height:36px;border-radius:50%;border:0;background:rgba(255,255,255,0.08);color:#fff;font-size:18px;cursor:pointer')}>
            ×
          </button>
        </div>
      )}
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        style={s('width:100%;max-width:560px;display:flex;flex-direction:column;gap:26px')}
      >
        {/* honeypot: bots fill it, people never see it */}
        <input ref={honeypot} name="website" tabIndex={-1} autoComplete="off" aria-hidden="true" style={s('position:absolute;left:-10000px;width:1px;height:1px;opacity:0')} />
        {keys.map(field)}
        {type !== 'callback' && (
          <div style={s('display:flex;flex-direction:column;align-items:center;gap:12px')}>
            <label style={sx('width:100%;display:flex;align-items:center;justify-content:center;gap:16px;padding:8px 4px 12px;border-bottom:1px solid rgb(204,21,23);font-weight:300;font-size:22px;color:rgb(184,184,184)', { cursor: n >= 5 ? 'default' : 'pointer', opacity: n >= 5 ? 0.5 : 1 })}>
              <input type="file" accept="image/*" multiple disabled={busy || n >= 5} onChange={(e) => { onFiles(e.target.files); e.target.value = ''; }} style={s('display:none')} />
              <span>Прикрепить фото</span>
              <span style={s('width:24px;height:34px;background:url(/assets/clip.webp) center / contain no-repeat;transform:rotate(40deg)')} />
            </label>
            <span style={sx('font-size:14px', { color: photoErr ? 'rgb(255,107,107)' : 'rgb(128,128,128)' })}>
              {photoErr || (n >= 5 ? '5 из 5 — больше добавить нельзя' : n ? `${n} из 5 · с камеры или из галереи` : 'До 5 фото — с камеры или из галереи')}
            </span>
            {n > 0 && (
              <div style={s('display:flex;flex-wrap:wrap;gap:10px;justify-content:center')}>
                {photos.map((p, i) => (
                  <div key={p.url} style={sx('position:relative;width:76px;height:76px;border-radius:13px', { background: `rgb(42,42,42) url(${p.url}) center / cover no-repeat` })}>
                    <button
                      type="button"
                      onClick={() => {
                        URL.revokeObjectURL(p.url);
                        setPhotos((ps) => ps.filter((_, j) => j !== i));
                        setPhotoErr('');
                        idem.current = null;
                      }}
                      aria-label="Удалить фото"
                      style={s('position:absolute;top:-8px;right:-8px;width:28px;height:28px;border-radius:50%;border:2px solid rgb(30,30,30);background:rgb(204,21,23);color:#fff;font-size:15px;line-height:1;cursor:pointer;padding:0')}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {type !== 'callback' && (
          <div style={s('display:flex;flex-direction:column;align-items:center;gap:14px;padding:18px;border-radius:13px;background:rgb(24,24,24)')}>
            <span style={s('font-size:15px;color:rgb(184,184,184);text-align:center')}>Пришлём статус заявки — укажите, куда удобнее (необязательно)</span>
            <div style={s('display:flex;flex-wrap:wrap;gap:16px;width:100%')}>
              {type !== 'corp' && (
                <div style={s('flex:1 1 200px;display:flex;flex-direction:column;align-items:center;gap:6px')}>
                  <input type="email" inputMode="email" autoComplete="email" value={email} maxLength={254} onChange={(e) => { setEmail(e.target.value); idem.current = null; revalidate(v, e.target.value); }} placeholder="E-mail" aria-label="E-mail для статуса заявки" disabled={busy} style={sx('width:100%;box-sizing:border-box;background:transparent;border:0;border-bottom:1px solid;padding:6px 4px 10px;color:#fff;font-family:K2D,Jost,sans-serif;font-weight:300;font-size:19px;text-align:center;outline:none;border-radius:0', { borderBottomColor: eLine('email') })} />
                  {errs.email && <span style={s('font-size:13px;color:rgb(255,107,107)')}>{errs.email}</span>}
                </div>
              )}
              <div style={s('flex:1 1 200px;display:flex;flex-direction:column;align-items:center;gap:6px')}>
                <input type="text" autoComplete="off" autoCapitalize="none" spellCheck={false} value={tg} maxLength={33} onChange={(e) => { setTg(e.target.value); idem.current = null; revalidate(v, email, e.target.value); }} placeholder="Telegram @ник" aria-label="Ник в Telegram для статуса заявки" disabled={busy} style={sx('width:100%;box-sizing:border-box;background:transparent;border:0;border-bottom:1px solid;padding:6px 4px 10px;color:#fff;font-family:K2D,Jost,sans-serif;font-weight:300;font-size:19px;text-align:center;outline:none;border-radius:0', { borderBottomColor: eLine('tg') })} />
                {errs.tg && <span style={s('font-size:13px;color:rgb(255,107,107)')}>{errs.tg}</span>}
              </div>
            </div>
          </div>
        )}
        <div data-err={errs.consent ? '1' : undefined} style={s('display:flex;flex-direction:column;align-items:center;gap:6px')}>
          <label style={s('display:flex;align-items:flex-start;gap:12px;cursor:pointer;max-width:480px;position:relative')}>
            <input type="checkbox" checked={consent} onChange={() => { setConsent(!consent); revalidate(v, email, tg, !consent); }} style={s('position:absolute;opacity:0;width:1px;height:1px')} />
            <span aria-hidden="true" style={sx('width:24px;height:24px;flex:none;border-radius:6px;border:1.5px solid;display:flex;align-items:center;justify-content:center;font-size:15px;line-height:1;margin-top:1px', { borderColor: errs.consent ? 'rgb(255,107,107)' : consent ? 'rgb(204,21,23)' : 'rgba(255,255,255,0.4)', background: consent ? 'rgb(204,21,23)' : 'transparent' })}>
              {consent ? '✓' : ''}
            </span>
            <span style={s('font-size:15px;line-height:1.4;color:rgb(184,184,184)')}>
              Согласен на обработку персональных данных по{' '}
              <Link to="/privacy" target="_blank" style={s('color:#fff;text-decoration:underline')}>
                политике
              </Link>
            </span>
          </label>
          {errs.consent && <span style={s('font-size:14px;color:rgb(255,107,107)')}>Нужно согласие, чтобы отправить заявку</span>}
        </div>
        <button type="submit" hidden />
      </form>
      {status === 'network' && (
        <div role="alert" style={s('width:100%;max-width:560px;box-sizing:border-box;display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:14px 18px;border-radius:13px;background:rgba(255,107,107,0.1);border:1px solid rgba(255,107,107,0.5)')}>
          <span style={s('flex:1 1 240px;font-size:16px')}>Не удалось отправить. Проверьте интернет и попробуйте ещё раз — данные сохранены.</span>
          <button onClick={() => void submit()} style={s('height:44px;padding:0 18px;border-radius:13px;border:1px solid #fff;background:transparent;color:#fff;font-family:K2D,Jost,sans-serif;font-size:16px;cursor:pointer')}>
            Повторить
          </button>
        </div>
      )}
      {(status === 'ratelimit' || status === 'error') && (
        <div role="alert" style={s('width:100%;max-width:560px;box-sizing:border-box;display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:14px 18px;border-radius:13px;background:oklch(0.82 0.16 85 / 0.12);border:1px solid oklch(0.82 0.16 85 / 0.6)')}>
          <span style={s('flex:1 1 240px;font-size:16px')}>{status === 'ratelimit' ? 'Слишком много заявок подряд. Позвоните — оформим по телефону.' : `${serverMsg}. Позвоните — оформим по телефону.`}</span>
          <a href={c.phoneHref} style={s('height:44px;padding:0 18px;border-radius:13px;background:rgb(204,21,23);color:#fff;display:flex;align-items:center;font-size:16px;text-decoration:none')}>
            Позвонить
          </a>
        </div>
      )}
      <div style={s('width:100%;display:flex;justify-content:flex-end')}>
        <button onClick={() => void submit()} disabled={busy} className="hv-accent" style={sx("min-width:233px;height:48px;padding:0 24px;border-radius:13px;border:0;color:#fff;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:28px;display:flex;align-items:center;justify-content:center;gap:12px;cursor:pointer;flex:0 1 auto", { background: busy ? 'rgb(150,20,22)' : 'rgb(204,21,23)', width: m ? '100%' : undefined })}>
          {busy && <span style={s('width:20px;height:20px;border-radius:50%;border:2px solid rgba(255,255,255,0.35);border-top-color:#fff;animation:gsspin .8s linear infinite;flex:none')} />}
          <span>{busy ? 'Отправляем…' : 'Завершить'}</span>
        </button>
      </div>
      {picker && (
        <div onClick={() => setPicker(false)} style={s('position:fixed;inset:0;z-index:80;background:rgba(0,0,0,0.72);display:flex;align-items:center;justify-content:center')}>
          <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Где сломались?" style={{ width: m ? '100%' : 'min(960px, 92vw)', height: m ? '100%' : 'min(680px, 88vh)', borderRadius: m ? 0 : 23, overflow: 'hidden' }}>
            <MapZone
              mode="picker"
              initial={(v.point as MapPoint) || null}
              onClose={() => setPicker(false)}
              onPick={(p) => {
                setPicker(false);
                const next = { ...v, point: p, addr: p.addr || (v.addr as string) || '' };
                setV(next);
                idem.current = null;
                revalidate(next);
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
