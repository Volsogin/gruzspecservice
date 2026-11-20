import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, API_URL, ApiError, type Estimate, type LeadCreated } from '../lib/api';
import { CHAT_EVENT, openForm, scrollToId, uiType, type UiFormType } from '../lib/bus';
import { s, sx } from '../lib/css';
import { fmtPhone, phoneDigits } from '../lib/format';
import { VEHICLE_SHORT, WORK_SHORT } from '../lib/labels';
import { useContacts, useSite, useWidth } from '../site';

type LinkKind = 'form' | 'map' | 'calc' | 'services';

type Msg =
  | { id: number; role: 'ai'; text: string; streaming?: boolean; sid?: number }
  | { id: number; role: 'user'; text: string }
  | { id: number; role: 'op'; text: string; name: string; sid?: number }
  | { id: number; role: 'sys'; text: string }
  | { id: number; role: 'typing'; text: string }
  | { id: number; role: 'err'; retry: string }
  | { id: number; role: 'limit' }
  | { id: number; role: 'price'; title: string; price: string; estimate: Estimate }
  | { id: number; role: 'link'; kind: LinkKind; type?: UiFormType; title: string; sub: string }
  | { id: number; role: 'order'; num: string; token: string; eta: number }
  | { id: number; role: 'phone'; title: string; done: boolean; needConsent: boolean };

type MsgInput = Msg extends infer M ? (M extends Msg ? Omit<M, 'id'> : never) : never;

interface SessionOut {
  session_id: string;
  status: 'bot' | 'waiting_operator' | 'operator' | 'closed';
  consent: boolean;
  has_phone: boolean;
  lead_id: string | null;
  messages: { id: number; role: 'user' | 'assistant' | 'operator'; text: string; suggested_replies: string[]; operator_name?: string | null }[];
  llm_enabled?: boolean | null;
  live_chat_available?: boolean | null;
}

interface ChatEvent {
  event: string;
  data: Record<string, unknown>;
}

const STORE_KEY = 'gs_chat_session';
const START_CHIPS = ['Сколько стоит ремонт?', 'Вызвать мастера', 'Нужна запчасть', 'Работаете с юрлицами?', 'Гарантия'];

const FORM_LINK: Record<string, [string, string]> = {
  onsite: ['Открыть форму вызова', 'Выезд мастера · 1–2 минуты'],
  tow: ['Вызвать эвакуатор', 'Точка на карте · 1–2 минуты'],
  parts: ['Запросить запчасть', 'Форма запроса'],
  corporate: ['Заявка для юрлиц', 'Корпоративное обслуживание'],
  repair: ['Записаться на ремонт', 'Ремонт на СТО'],
  callback: ['Перезвоните мне', 'Оставьте номер — перезвоним'],
};

/** The model is told to answer in plain text, but strip stray markdown just in case. */
function plain(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, '$1').replace(/\*\*/g, '').replace(/^#{1,6}\s+/gm, '').replace(/^\s*[*-]\s+/gm, '— ');
}

function storeGet(): string | null {
  try {
    return sessionStorage.getItem(STORE_KEY);
  } catch {
    return null;
  }
}
function storeSet(v: string | null) {
  try {
    if (v) sessionStorage.setItem(STORE_KEY, v);
    else sessionStorage.removeItem(STORE_KEY);
  } catch {
    /* private mode */
  }
}

/** Parses an SSE stream from a fetch() body (EventSource can't POST). */
async function* readSse(res: Response): AsyncGenerator<ChatEvent> {
  const reader = res.body!.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = 'message';
      const data: string[] = [];
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
      }
      try {
        yield { event, data: data.length ? JSON.parse(data.join('\n')) : {} };
      } catch {
        /* skip malformed frame */
      }
    }
  }
}

export function Chat() {
  const w = useWidth();
  const m = w < 1100;
  const navigate = useNavigate();
  const c = useContacts();
  const site = useSite().data;
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [chips, setChips] = useState<string[]>([]);
  const [draft, setDraft] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<SessionOut['status']>('bot');
  const [opName, setOpName] = useState('');
  const [consented, setConsented] = useState(false);
  const [needConsent, setNeedConsent] = useState(false);
  const [consentBox, setConsentBox] = useState(false);
  const [phone, setPhone] = useState('');
  const [phoneErr, setPhoneErr] = useState('');
  const [limit, setLimit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [handedOff, setHandedOff] = useState(false);
  const [liveAvailable, setLiveAvailable] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const uid = useRef(1);
  const sessionRef = useRef<string | null>(null);
  const starting = useRef<Promise<string | null> | null>(null);
  const seenOp = useRef(new Set<number>());
  const opNameRef = useRef('');

  const push = useCallback((...ms: MsgInput[]) => {
    setMsgs((cur) => [...cur.filter((x) => x.role !== 'typing'), ...ms.map((x) => ({ ...x, id: uid.current++ }) as Msg)]);
  }, []);

  useEffect(() => {
    const l = listRef.current;
    if (l) l.scrollTop = l.scrollHeight;
  }, [msgs, chips, open]);

  useEffect(() => {
    if (!(m && open)) return;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, [m, open]);

  const applySession = (sess: SessionOut, restore: boolean) => {
    sessionRef.current = sess.session_id;
    setSessionId(sess.session_id);
    storeSet(sess.session_id);
    setStatus(sess.status);
    setConsented(sess.consent);
    setLiveAvailable(!!sess.live_chat_available);
    if (sess.lead_id) setHandedOff(true);
    const restored: MsgInput[] = [{ role: 'sys', text: 'ИИ-помощник отвечает сразу. Оператор — по кнопке выше' }];
    for (const x of sess.messages) {
      if (x.role === 'user') restored.push({ role: 'user', text: x.text });
      else if (x.role === 'operator') {
        seenOp.current.add(x.id);
        restored.push({ role: 'op', text: x.text, name: x.operator_name || 'Оператор', sid: x.id });
        opNameRef.current = x.operator_name || 'Оператор';
        setOpName(opNameRef.current);
      } else if (x.text) restored.push({ role: 'ai', text: x.text, sid: x.id });
    }
    setMsgs(restored.map((x) => ({ ...x, id: uid.current++ }) as Msg));
    const last = [...sess.messages].reverse().find((x) => x.role === 'assistant');
    setChips(restore ? last?.suggested_replies || [] : last?.suggested_replies?.length ? last.suggested_replies : START_CHIPS);
  };

  const ensureSession = (): Promise<string | null> => {
    if (sessionRef.current) return Promise.resolve(sessionRef.current);
    if (starting.current) return starting.current;
    starting.current = (async () => {
      const saved = storeGet();
      if (saved) {
        try {
          const sess = await api<SessionOut>(`/chat/sessions/${saved}/messages`);
          if (sess.status !== 'closed') {
            applySession(sess, true);
            return sess.session_id;
          }
        } catch {
          storeSet(null);
        }
      }
      try {
        const sess = await api<SessionOut>('/chat/sessions', { method: 'POST', json: { consent: false } });
        applySession(sess, false);
        return sess.session_id;
      } catch {
        setMsgs([{ id: uid.current++, role: 'err', retry: '' }]);
        return null;
      } finally {
        starting.current = null;
      }
    })();
    return starting.current;
  };

  const openChat = useCallback(() => {
    setOpen(true);
    void ensureSession();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    window.addEventListener(CHAT_EVENT, openChat);
    return () => window.removeEventListener(CHAT_EVENT, openChat);
  }, [openChat]);

  // Live operator replies (level B): long-lived SSE while waiting for / talking to an operator.
  useEffect(() => {
    if (!sessionId || (status !== 'waiting_operator' && status !== 'operator')) return;
    const es = new EventSource(`${API_URL}/chat/sessions/${sessionId}/events`);
    const addOp = (id: number, text: string, name: string) => {
      if (seenOp.current.has(id)) return;
      seenOp.current.add(id);
      if (!opNameRef.current) push({ role: 'sys', text: `Оператор ${name} в чате` });
      opNameRef.current = name;
      setOpName(name);
      push({ role: 'op', text, name, sid: id });
    };
    es.addEventListener('operator_message', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data);
        addOp(d.id, d.text, d.operator_name || 'Оператор');
        if (d.session_status) setStatus(d.session_status);
      } catch {
        /* ignore */
      }
    });
    es.addEventListener('ready', () => {
      // Catch up on replies sent while the stream was disconnected.
      api<SessionOut>(`/chat/sessions/${sessionId}/messages`)
        .then((sess) => {
          sess.messages.filter((x) => x.role === 'operator').forEach((x) => addOp(x.id, x.text, x.operator_name || 'Оператор'));
          setStatus(sess.status);
        })
        .catch(() => {});
    });
    return () => es.close();
  }, [sessionId, status === 'bot' || status === 'closed']); // eslint-disable-line react-hooks/exhaustive-deps

  const estimateTitle = (e: Estimate): string => {
    const brand = site?.brands.find((b) => b.slug === e.input.brand)?.title || e.input.brand;
    const parts = [WORK_SHORT[e.input.work_type] || e.input.work_type, brand];
    if (e.input.vehicle_type) parts.push((VEHICLE_SHORT[e.input.vehicle_type] || e.input.vehicle_type).toLowerCase());
    parts.push(e.input.onsite ? 'с выездом' : 'на СТО');
    return parts.join(' · ');
  };

  /** Turns backend events into cards; returns cards to show after the reply text. */
  const handleEvent = (ev: ChatEvent, cards: MsgInput[]) => {
    const d = ev.data;
    if (ev.event === 'estimate') {
      const e = d as unknown as Estimate;
      cards.push({ role: 'price', title: estimateTitle(e), price: e.price_label, estimate: e });
    } else if (ev.event === 'action') {
      const t = d.type as string;
      if (t === 'open_form') {
        const ft = String(d.form_type || 'onsite');
        const [title, sub] = FORM_LINK[ft] || FORM_LINK.onsite;
        cards.push({ role: 'link', kind: 'form', type: uiType(ft), title, sub });
      } else if (t === 'show_map') cards.push({ role: 'link', kind: 'map', title: 'Показать на карте', sub: 'Проверить, попадаете ли в зону' });
      else if (t === 'open_calculator') cards.push({ role: 'link', kind: 'calc', title: 'Открыть калькулятор', sub: 'Посчитать стоимость за минуту' });
      else if (t === 'show_services') cards.push({ role: 'link', kind: 'services', title: 'Посмотреть услуги', sub: 'На СТО и с выездом' });
      else if (t === 'phone_required') {
        cards.push({ role: 'phone', title: 'Оставьте телефон — оператор перезвонит', done: false, needConsent: !!d.consent_required });
      } else if (t === 'consent_required') setNeedConsent(true);
      else if (t === 'lead_created') {
        const lead = d.lead as LeadCreated;
        setHandedOff(true);
        cards.push({ role: 'order', num: lead.number, token: lead.public_token, eta: lead.callback_eta_minutes });
      }
    } else if (ev.event === 'handoff') {
      const st = String(d.status || '');
      const live = !!d.live_chat;
      setLiveAvailable(live);
      if (st === 'waiting_operator') {
        setStatus('waiting_operator');
        cards.push({ role: 'sys', text: 'Ждём оператора… обычно до 2 минут' });
      } else if (st === 'operator') setStatus('operator');
    }
  };

  const send = async (text: string, isRetry = false) => {
    const t = text.trim();
    if (!t || limit || busy) return;
    setDraft('');
    setChips([]);
    if (!isRetry) push({ role: 'user', text: t });
    setMsgs((cur) => [...cur.filter((x) => x.role !== 'err' && x.role !== 'typing'), { id: uid.current++, role: 'typing', text: status === 'operator' ? `${opName || 'Оператор'} печатает` : 'печатает' }]);
    setBusy(true);
    const consentNow = consented || consentBox;
    try {
      let id = await ensureSession();
      if (!id) throw new ApiError(0, 'network', '');
      const post = () =>
        fetch(`${API_URL}/chat/sessions/${id}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
          body: JSON.stringify({ text: t, consent: consentNow }),
        });
      let res = await post();
      if (res.status === 404) {
        // Session expired on the server: start a new one and resend.
        sessionRef.current = null;
        storeSet(null);
        id = await ensureSession();
        if (!id) throw new ApiError(0, 'network', '');
        res = await post();
      }
      if (!res.ok) {
        let code = `http_${res.status}`;
        try {
          code = (await res.json())?.error?.code || code;
        } catch {
          /* not json */
        }
        if (res.status === 429 && code === 'chat_limit') {
          setLimit(true);
          push({ role: 'limit' });
          return;
        }
        throw new ApiError(res.status, code, '');
      }
      if (consentNow) {
        setConsented(true);
        setNeedConsent(false);
      }
      const aiId = uid.current++;
      let text = '';
      let started = false;
      const cards: MsgInput[] = [];
      const upsert = (streaming: boolean) => {
        setMsgs((cur) => {
          const rest = cur.filter((x) => x.role !== 'typing');
          const i = rest.findIndex((x) => x.id === aiId);
          const msg: Msg = { id: aiId, role: 'ai', text, streaming };
          if (i >= 0) {
            const copy = rest.slice();
            copy[i] = msg;
            return copy;
          }
          return [...rest, msg];
        });
      };
      for await (const ev of readSse(res)) {
        if (ev.event === 'delta') {
          text += String(ev.data.text || '');
          started = true;
          upsert(true);
        } else if (ev.event === 'reset') {
          text = '';
          if (started) upsert(true);
        } else if (ev.event === 'done') {
          const d = ev.data;
          if (d.text && typeof d.text === 'string') text = d.text;
          if (text) upsert(false);
          else setMsgs((cur) => cur.filter((x) => x.role !== 'typing'));
          if (cards.length) push(...cards);
          cards.length = 0;
          setChips(Array.isArray(d.suggested_replies) ? (d.suggested_replies as string[]) : []);
          if (d.session_status) setStatus(d.session_status as SessionOut['status']);
        } else if (ev.event === 'error') {
          if (ev.data.code === 'chat_limit') {
            setLimit(true);
            push({ role: 'limit' });
          } else push({ role: 'err', retry: t });
        } else handleEvent(ev, cards);
      }
      if (cards.length) push(...cards);
      setMsgs((cur) => cur.filter((x) => x.role !== 'typing'));
    } catch {
      push({ role: 'err', retry: t });
    } finally {
      setBusy(false);
    }
  };

  const callOp = async (withPhone?: { phone: string; msgId: number }) => {
    const id = await ensureSession();
    if (!id) return;
    setChips([]);
    try {
      const body: Record<string, unknown> = { consent: consented || consentBox || !!withPhone };
      if (withPhone) body.phone = withPhone.phone;
      const r = await api<{ status: SessionOut['status']; message: string; events: ChatEvent[] }>(`/chat/sessions/${id}/handoff`, { method: 'POST', json: body });
      if (withPhone) {
        setMsgs((cur) => cur.map((x) => (x.id === withPhone.msgId && x.role === 'phone' ? { ...x, done: true } : x)));
        setConsented(true);
      } else push({ role: 'user', text: 'Позвать оператора' });
      const cards: MsgInput[] = [];
      let done: string[] = [];
      for (const ev of r.events) {
        if (ev.event === 'done') done = (ev.data.suggested_replies as string[]) || [];
        else handleEvent(ev, cards);
      }
      push({ role: 'ai', text: r.message }, ...cards);
      setStatus(r.status);
      setChips(done);
    } catch (e) {
      if (withPhone && e instanceof ApiError && e.status === 422) {
        setPhoneErr(e.fields.phone || e.fields.consent || e.message);
        return;
      }
      push({ role: 'err', retry: '' });
    }
  };

  const submitPhone = (msgId: number, need: boolean) => {
    if (phoneDigits(phone).length < 11) return setPhoneErr('Номер неполный');
    if (need && !consented && !consentBox) return setPhoneErr('Нужно согласие на обработку данных');
    setPhoneErr('');
    void callOp({ phone, msgId });
  };

  const goForm = (type: UiFormType, extra: Parameters<typeof openForm>[0] = {}) => {
    if (m) setOpen(false);
    openForm({ type, ...extra }, navigate);
  };
  const goSection = (id: string) => {
    if (m) setOpen(false);
    scrollToId(id, navigate);
  };

  const pick = (chip: string) => {
    if (/оператор/i.test(chip) && status === 'bot' && !handedOff) return void callOp();
    void send(chip);
  };

  const live = status === 'operator';
  const waiting = status === 'waiting_operator';
  const head: [string, string, string] = live
    ? [`Оператор ${opName || ''} в чате`.replace('  ', ' '), 'Живой диспетчер', 'oklch(0.72 0.12 240)']
    : waiting
      ? ['Ждём оператора…', 'Обычно до 2 минут', 'oklch(0.82 0.16 85)']
      : ['Помощник', 'ИИ · отвечает сразу', 'oklch(0.72 0.17 150)'];
  const canCallOp = status === 'bot' && !limit && !handedOff;
  const showConsentRow = !consented && (needConsent || /\d{3}\D?\d{3}\D?\d{2}\D?\d{2}/.test(draft));
  const icon: Record<LinkKind, [string, string]> = {
    form: ['/assets/clip.webp', 'none'],
    map: ['/assets/icon-b.webp', 'invert(1)'],
    calc: ['/assets/icon-a.webp', 'invert(1)'],
    services: ['/assets/clip.webp', 'none'],
  };

  const checkbox = (checked: boolean, size: number) => (
    <span aria-hidden="true" style={sx('flex:none;border:1.5px solid;display:flex;align-items:center;justify-content:center;font-size:13px', { width: size, height: size, borderRadius: size > 20 ? 6 : 5, borderColor: checked ? 'rgb(204,21,23)' : 'rgba(255,255,255,0.4)', background: checked ? 'rgb(204,21,23)' : 'transparent' })}>
      {checked ? '✓' : ''}
    </span>
  );
  const consentLabel = (
    <label style={s('display:flex;gap:10px;align-items:flex-start;cursor:pointer;font-size:13px;line-height:1.4;color:rgb(184,184,184);position:relative')}>
      <input type="checkbox" checked={consentBox} onChange={() => { setConsentBox(!consentBox); setPhoneErr(''); }} style={s('position:absolute;opacity:0;width:1px;height:1px')} />
      {checkbox(consentBox, 20)}
      <span>
        Согласен на обработку персональных данных по{' '}
        <Link to="/privacy" target="_blank" style={s('color:#fff;text-decoration:underline')}>
          политике
        </Link>
      </span>
    </label>
  );

  const render = (x: Msg): ReactNode => {
    switch (x.role) {
      case 'ai':
        return (
          <div key={x.id} style={s('align-self:flex-start;max-width:86%;padding:11px 14px;border-radius:4px 16px 16px 16px;background:rgb(42,42,42);font-size:16px;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere')}>
            {plain(x.text)}
            {x.streaming ? <span style={s('animation:gscaret 1s steps(1) infinite')}>▍</span> : null}
          </div>
        );
      case 'user':
        return (
          <div key={x.id} style={s('align-self:flex-end;max-width:80%;padding:11px 14px;border-radius:16px 4px 16px 16px;background:rgb(204,21,23);font-size:16px;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere')}>
            {x.text}
          </div>
        );
      case 'op':
        return (
          <div key={x.id} style={s('align-self:flex-start;max-width:86%;display:flex;gap:8px;align-items:flex-end')}>
            <div style={s('width:30px;height:30px;flex:none;border-radius:50%;background:oklch(0.72 0.12 240);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600;color:rgb(18,18,18)')}>{(x.name || 'О').slice(0, 1).toUpperCase()}</div>
            <div style={s('display:flex;flex-direction:column;gap:4px;padding:10px 14px;border-radius:16px 16px 16px 4px;background:rgb(18,18,18);border:1px solid oklch(0.72 0.12 240 / 0.7)')}>
              <span style={s('font-size:12px;color:oklch(0.8 0.1 240)')}>{x.name} · оператор</span>
              <span style={s('font-size:16px;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere')}>{x.text}</span>
            </div>
          </div>
        );
      case 'sys':
        return (
          <div key={x.id} style={s('align-self:center;display:flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;background:rgba(255,255,255,0.06);font-size:13px;color:rgb(184,184,184);text-align:center')}>
            {x.text}
          </div>
        );
      case 'typing':
        return (
          <div key={x.id} style={s('align-self:flex-start;display:flex;align-items:center;gap:8px;padding:12px 14px;border-radius:4px 16px 16px 16px;background:rgb(42,42,42);font-size:13px;color:rgb(184,184,184)')}>
            <span style={s('display:inline-flex;gap:3px')}>
              {[0, 1, 2].map((i) => (
                <span key={i} style={{ width: 6, height: 6, borderRadius: '50%', background: '#fff', animation: `gsdot 1.1s ${i * 0.15}s infinite` }} />
              ))}
            </span>
            <span>{x.text}</span>
          </div>
        );
      case 'err':
        return (
          <div key={x.id} role="alert" style={s('align-self:stretch;display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:13px;background:rgba(255,107,107,0.1);border:1px solid rgba(255,107,107,0.45);font-size:14px')}>
            <span style={s('flex:1')}>Связь пропала, повторите</span>
            <button
              onClick={() => {
                setMsgs((cur) => cur.filter((y) => y.id !== x.id));
                if (x.retry) void send(x.retry, true);
                else void ensureSession();
              }}
              style={s('height:36px;padding:0 14px;border-radius:10px;border:1px solid #fff;background:transparent;color:#fff;font-family:K2D,Jost,sans-serif;font-size:14px;cursor:pointer')}
            >
              Повторить
            </button>
          </div>
        );
      case 'limit':
        return (
          <div key={x.id} style={s('align-self:stretch;display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:13px;background:oklch(0.82 0.16 85 / 0.12);border:1px solid oklch(0.82 0.16 85 / 0.55);font-size:14px')}>
            <span style={s('flex:1')}>Лимит сообщений — позвоните нам</span>
            <a href={c.phoneHref} style={s('height:36px;padding:0 14px;border-radius:10px;background:rgb(204,21,23);color:#fff;display:flex;align-items:center;font-size:14px;text-decoration:none')}>
              Позвонить
            </a>
          </div>
        );
      case 'price':
        return (
          <div key={x.id} style={s('align-self:flex-start;width:86%;box-sizing:border-box;display:flex;flex-direction:column;gap:6px;padding:16px;border-radius:16px;background:linear-gradient(214deg, rgb(0,0,0) 5%, rgb(102,102,102) 116%)')}>
            <span style={s('font-size:13px;color:rgb(184,184,184)')}>{x.title}</span>
            <span style={s('font-weight:100;font-size:40px;line-height:1')}>{x.price}</span>
            <span style={s('font-size:12px;color:rgb(150,150,150)')}>Цены условные, точную стоимость назовёт мастер</span>
            <button
              onClick={() =>
                goForm(x.estimate.input.onsite ? 'visit' : 'sto', {
                  calc: { estimateId: x.estimate.estimate_id, total: x.price, desc: x.title.toLowerCase(), onsite: x.estimate.input.onsite },
                })
              }
              style={s("margin-top:6px;height:44px;border-radius:13px;border:0;background:rgb(204,21,23);color:#fff;font-family:'Josefin Sans',Jost,sans-serif;font-size:18px;cursor:pointer")}
            >
              Оставить заявку
            </button>
          </div>
        );
      case 'link':
        return (
          <button
            key={x.id}
            onClick={() => {
              if (x.kind === 'form') goForm(x.type || 'visit');
              else if (x.kind === 'map') goSection('zone');
              else if (x.kind === 'calc') goSection('prices');
              else goSection('services');
            }}
            className="hv-bd-accent"
            style={s('align-self:flex-start;width:86%;display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:13px;border:1px solid rgba(255,255,255,0.16);background:rgb(24,24,24);color:#fff;font-family:K2D,Jost,sans-serif;text-align:left;cursor:pointer')}
          >
            <span style={sx('width:36px;height:36px;flex:none;border-radius:10px', { background: `rgb(42,42,42) url(${icon[x.kind][0]}) center / 18px no-repeat`, filter: icon[x.kind][1] })} />
            <span style={s('flex:1;display:flex;flex-direction:column;gap:2px')}>
              <span style={s('font-size:16px')}>{x.title}</span>
              <span style={s('font-size:13px;color:rgb(184,184,184)')}>{x.sub}</span>
            </span>
            <span style={s('font-size:18px;color:rgb(204,21,23)')}>→</span>
          </button>
        );
      case 'order':
        return (
          <div key={x.id} style={s('align-self:flex-start;width:86%;box-sizing:border-box;display:flex;flex-direction:column;gap:8px;padding:16px;border-radius:16px;background:oklch(0.72 0.17 150 / 0.12);border:1px solid oklch(0.72 0.17 150 / 0.55)')}>
            <span style={s('font-size:13px;color:oklch(0.85 0.12 150)')}>Заявка создана</span>
            <span style={s('font-weight:300;font-size:30px;line-height:1')}>{x.num}</span>
            <span style={s('font-size:14px;color:rgb(184,184,184)')}>Диспетчер перезвонит в течение {x.eta} минут</span>
            <Link to={`/order/${x.token}`} onClick={() => m && setOpen(false)} style={s('height:44px;border-radius:13px;border:1px solid #fff;color:#fff;display:flex;align-items:center;justify-content:center;font-size:15px;text-decoration:none')}>
              Открыть статус заявки
            </Link>
          </div>
        );
      case 'phone': {
        const need = x.needConsent && !consented;
        return (
          <div key={x.id} style={s('align-self:stretch;display:flex;flex-direction:column;gap:12px;padding:16px;border-radius:16px;background:rgb(24,24,24);border:1px solid rgba(255,255,255,0.14)')}>
            <span style={s('font-size:16px')}>{x.title}</span>
            <input type="tel" inputMode="tel" autoComplete="tel" value={phone} onChange={(e) => { setPhone(fmtPhone(e.target.value)); setPhoneErr(''); }} placeholder="+7 (___) ___-__-__" disabled={x.done} aria-label="Телефон" style={sx('height:48px;box-sizing:border-box;padding:0 14px;border-radius:13px;border:1px solid;background:rgb(42,42,42);color:#fff;font-family:K2D,Jost,sans-serif;font-size:18px;outline:none', { borderColor: phoneErr && !x.done ? 'rgb(255,107,107)' : 'rgba(255,255,255,0.12)' })} />
            {need && !x.done && consentLabel}
            {phoneErr && !x.done && <span style={s('font-size:13px;color:rgb(255,107,107)')}>{phoneErr}</span>}
            <button onClick={() => !x.done && submitPhone(x.id, need)} disabled={x.done} style={sx("height:44px;border-radius:13px;border:0;color:#fff;font-family:'Josefin Sans',Jost,sans-serif;font-size:18px;cursor:pointer", { background: x.done ? 'rgb(58,58,58)' : 'rgb(204,21,23)' })}>
              {x.done ? 'Отправлено' : 'Позвать оператора'}
            </button>
          </div>
        );
      }
    }
  };

  return (
    <>
      {!m && !open && (
        <button onClick={openChat} aria-label="Открыть чат" className="hv-accent" style={s('position:fixed;right:16px;bottom:16px;z-index:50;width:111px;height:111px;border-radius:50%;border:0;background:rgb(204,21,23);cursor:pointer;padding:0;box-shadow:0 10px 30px rgba(0,0,0,0.5)')}>
          <span style={s('position:absolute;left:-14px;top:-26px;width:139px;height:118px;background:url(/assets/mascot-head.webp) center / contain no-repeat')} />
        </button>
      )}
      {open && (
        <div role="dialog" aria-label="Чат с помощником" style={sx('position:fixed;z-index:70;top:0;right:0;bottom:0;background:rgb(30,30,30);display:flex;flex-direction:column;font-family:K2D,Jost,sans-serif;color:#fff;box-shadow:-20px 0 60px rgba(0,0,0,0.5);border-left:1px solid rgba(255,255,255,0.08)', { left: m ? 0 : 'auto', width: m ? 'auto' : 420, height: m ? '100dvh' : undefined })}>
          <div style={s('display:flex;align-items:center;gap:12px;padding:12px 12px 12px 16px;border-bottom:1px solid rgba(255,255,255,0.08)')}>
            <div style={s('width:44px;height:44px;flex:none;border-radius:50%;background:rgb(204,21,23) url(/assets/mascot-head.webp) 86% 50% / 120% no-repeat')} />
            <div style={s('flex:1;min-width:0;display:flex;flex-direction:column;gap:2px')}>
              <span style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:20px;line-height:1.1")}>{head[0]}</span>
              <span style={s('display:flex;align-items:center;gap:6px;font-size:13px;color:rgb(184,184,184)')}>
                <span style={sx('width:7px;height:7px;border-radius:50%', { background: head[2] })} />
                {head[1]}
              </span>
            </div>
            <button onClick={() => setOpen(false)} aria-label="Закрыть чат" style={s('width:44px;height:44px;flex:none;border-radius:13px;border:0;background:rgb(42,42,42);color:#fff;font-size:22px;cursor:pointer')}>
              ×
            </button>
          </div>
          {canCallOp && (
            <button onClick={() => void callOp()} className="hv-bd-accent" style={s('margin:10px 12px 0;height:40px;border-radius:13px;border:1px solid rgba(255,255,255,0.18);background:transparent;color:#fff;font-family:K2D,Jost,sans-serif;font-size:15px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px')}>
              <span style={s('width:8px;height:8px;border-radius:50%;background:rgb(204,21,23)')} />
              {liveAvailable ? 'Позвать оператора' : 'Позвать оператора (перезвоним)'}
            </button>
          )}
          <div ref={listRef} aria-live="polite" style={s('flex:1;min-height:0;overflow-y:auto;padding:16px 12px;display:flex;flex-direction:column;gap:10px;overscroll-behavior:contain')}>
            {msgs.map(render)}
            {chips.length > 0 && !limit && !busy && (
              <div style={s('display:flex;flex-wrap:wrap;gap:6px;padding-top:2px')}>
                {chips.map((chip) => (
                  <button key={chip} onClick={() => pick(chip)} className="hv-soft" style={s('min-height:36px;padding:6px 12px;border-radius:999px;border:1px solid rgba(204,21,23,0.7);background:transparent;color:#fff;font-family:K2D,Jost,sans-serif;font-size:14px;cursor:pointer')}>
                    {chip}
                  </button>
                ))}
              </div>
            )}
          </div>
          {showConsentRow && <div style={s('padding:8px 12px 0;border-top:1px solid rgba(255,255,255,0.08)')}>{consentLabel}</div>}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void send(draft);
            }}
            style={s('display:flex;gap:8px;padding:10px 12px calc(10px + env(safe-area-inset-bottom));border-top:1px solid rgba(255,255,255,0.08);background:rgb(30,30,30)')}
          >
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={limit}
              maxLength={1000}
              placeholder={limit ? 'Лимит сообщений исчерпан' : live ? `Сообщение ${opName || 'оператору'}` : 'Опишите поломку или задайте вопрос'}
              enterKeyHint="send"
              aria-label="Сообщение"
              className="fc-accent"
              style={s('flex:1;min-width:0;height:48px;box-sizing:border-box;padding:0 14px;border-radius:13px;border:1px solid rgba(255,255,255,0.12);background:rgb(42,42,42);color:#fff;font-family:K2D,Jost,sans-serif;font-size:16px;outline:none')}
            />
            <button type="submit" disabled={limit || busy} aria-label="Отправить" style={sx('width:48px;height:48px;flex:none;border-radius:13px;border:0;color:#fff;font-size:20px;cursor:pointer', { background: draft.trim() && !busy ? 'rgb(204,21,23)' : 'rgb(58,58,58)' })}>
              ↑
            </button>
          </form>
        </div>
      )}
    </>
  );
}
