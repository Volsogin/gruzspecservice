import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError, type CalcOptions, type Estimate } from '../lib/api';
import { openForm } from '../lib/bus';
import { s, sx } from '../lib/css';
import { rub } from '../lib/format';
import { VEHICLE_ORDER, VEHICLE_SHORT, WORK_SHORT } from '../lib/labels';

const WORK_ORDER = ['diagnostics', 'maintenance', 'chassis', 'brakes', 'engine', 'electrics', 'transmission', 'pneumatics', 'fuel'];

const CHIP =
  'min-height:44px;padding:0 16px;border-radius:999px;border:1px solid;color:#fff;font-family:K2D,Jost,sans-serif;font-size:16px;cursor:pointer';
const chip = (act: boolean) => ({ background: act ? 'rgb(204,21,23)' : 'transparent', borderColor: act ? 'rgb(204,21,23)' : 'rgba(255,255,255,0.22)' });

export function Calculator() {
  const navigate = useNavigate();
  const [opts, setOpts] = useState<CalcOptions | null>(null);
  const [optsErr, setOptsErr] = useState(false);
  const [brand, setBrand] = useState('man');
  const [brandQuery, setBrandQuery] = useState('MAN');
  const [brandsOpen, setBrandsOpen] = useState(false);
  const [vt, setVt] = useState('tractor');
  const [work, setWork] = useState('chassis');
  const [urgent, setUrgent] = useState(false);
  const [onsite, setOnsite] = useState(false);
  const [est, setEst] = useState<Estimate | null>(null);
  const [loading, setLoading] = useState(false);
  const [calcErr, setCalcErr] = useState('');
  const [breakOpen, setBreakOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api<CalcOptions>('/calculator/options').then(setOpts).catch(() => setOptsErr(true));
  }, []);

  // Recalculate on the server (single source of prices), debounced.
  useEffect(() => {
    if (!opts) return;
    setLoading(true);
    const t = setTimeout(() => {
      api<Estimate>('/calculator/estimate', { method: 'POST', json: { brand, work_type: work, vehicle_type: vt, urgent, onsite } })
        .then((e) => {
          setEst(e);
          setCalcErr('');
        })
        .catch((e) => setCalcErr(e instanceof ApiError && e.status === 429 ? 'Слишком много расчётов — подождите минуту' : 'Не удалось посчитать — попробуйте ещё раз'))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(t);
  }, [opts, brand, work, vt, urgent, onsite]);

  useEffect(() => {
    if (!brandsOpen) return;
    const close = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setBrandsOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [brandsOpen]);

  const brands = opts?.brands || [];
  const brandTitle = brands.find((b) => b.slug === brand)?.title || 'MAN';
  const bq = brandQuery.trim().toLowerCase();
  const brandOpts = brands.filter((b) => !bq || b.title.toLowerCase().includes(bq));
  const types = useMemo(
    () => (opts?.vehicle_types || []).slice().sort((a, b) => VEHICLE_ORDER.indexOf(a.slug) - VEHICLE_ORDER.indexOf(b.slug)),
    [opts],
  );
  const works = useMemo(
    () =>
      (opts?.work_types || [])
        .filter((w) => !w.is_onsite_service)
        .sort((a, b) => (WORK_ORDER.indexOf(a.slug) + 99) % 99 - ((WORK_ORDER.indexOf(b.slug) + 99) % 99)),
    [opts],
  );
  const vtLabel = VEHICLE_SHORT[vt] || types.find((t) => t.slug === vt)?.title || '';
  const workLabel = WORK_SHORT[work] || works.find((w) => w.slug === work)?.title || '';
  const summary = `${brandTitle} · ${vtLabel} · ${workLabel}${onsite ? ' · с выездом' : ''}${urgent ? ' · срочно' : ''}`;
  const total = est ? est.price_label.replace(/ (?=\d{3})/g, ' ') : '—';
  const pct = opts?.surcharges.urgent_pct ?? 20;
  const fee = opts?.surcharges.onsite_fee ?? 0;

  const toForm = () => {
    if (!est) return;
    openForm(
      {
        type: onsite ? 'visit' : 'sto',
        calc: {
          estimateId: est.estimate_id,
          total,
          desc: `${brandTitle}, ${vtLabel.toLowerCase()}, ${workLabel.toLowerCase()}${onsite ? ', с выездом' : ''}${urgent ? ', срочно' : ''}`,
          onsite,
        },
      },
      navigate,
    );
  };

  if (optsErr) {
    return (
      <div style={s('background:rgb(30,30,30);border-radius:23px;padding:32px;font-size:17px;color:rgb(184,184,184)')}>
        Калькулятор сейчас недоступен. Оставьте заявку — мастер назовёт стоимость.
      </div>
    );
  }

  return (
    <div style={s('display:flex;flex-wrap:wrap;gap:20px')}>
      <div style={s('flex:1 1 520px;min-width:0;background:rgb(30,30,30);border-radius:23px;padding:clamp(18px,2.4vw,32px);display:flex;flex-direction:column;gap:24px')}>
        <div ref={boxRef} style={s('display:flex;flex-direction:column;gap:8px;position:relative')}>
          <span style={s('font-size:14px;color:rgb(184,184,184)')}>Марка</span>
          <input
            value={brandQuery}
            onChange={(e) => {
              setBrandQuery(e.target.value);
              setBrandsOpen(true);
              const hit = brands.find((b) => b.title.toLowerCase() === e.target.value.trim().toLowerCase());
              if (hit) setBrand(hit.slug);
            }}
            onFocus={() => {
              setBrandsOpen(true);
              setBrandQuery('');
            }}
            onBlur={() => setTimeout(() => setBrandQuery((q) => (brands.some((b) => b.title === q) ? q : brandTitle)), 150)}
            placeholder="Начните вводить: MAN, КамАЗ…"
            aria-label="Марка"
            className="fc-accent"
            style={s('height:52px;box-sizing:border-box;padding:0 16px;border-radius:13px;border:1px solid rgba(255,255,255,0.12);background:rgb(42,42,42);color:#fff;font-family:K2D,Jost,sans-serif;font-size:18px;outline:none')}
          />
          {brandsOpen && (
            <div style={s('position:absolute;left:0;right:0;top:84px;z-index:6;max-height:260px;overflow-y:auto;background:rgb(42,42,42);border-radius:13px;box-shadow:0 12px 32px rgba(0,0,0,0.5)')}>
              {brandOpts.map((b) => (
                <button
                  key={b.slug}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    setBrand(b.slug);
                    setBrandQuery(b.title);
                    setBrandsOpen(false);
                  }}
                  className="hv-s3"
                  style={s('display:flex;justify-content:space-between;width:100%;padding:12px 16px;border:0;background:transparent;color:#fff;font-family:K2D,Jost,sans-serif;font-size:16px;cursor:pointer;text-align:left')}
                >
                  <span>{b.title}</span>
                  <span style={s('color:rgb(128,128,128);font-size:13px')}>{b.origin_label}</span>
                </button>
              ))}
              {brandOpts.length === 0 && (
                <span style={s('display:block;padding:12px 16px;color:rgb(184,184,184);font-size:15px')}>Не нашли марку — выберите похожую или оставьте заявку, мастер посчитает</span>
              )}
            </div>
          )}
        </div>
        <div style={s('display:flex;flex-direction:column;gap:8px')}>
          <span style={s('font-size:14px;color:rgb(184,184,184)')}>Тип техники</span>
          <div style={s('display:flex;flex-wrap:wrap;gap:8px')}>
            {types.map((t) => (
              <button key={t.slug} aria-pressed={t.slug === vt} onClick={() => setVt(t.slug)} style={sx(CHIP, chip(t.slug === vt))}>
                {VEHICLE_SHORT[t.slug] || t.title}
              </button>
            ))}
          </div>
        </div>
        <div style={s('display:flex;flex-direction:column;gap:8px')}>
          <span style={s('font-size:14px;color:rgb(184,184,184)')}>Вид работ</span>
          <div style={s('display:flex;flex-wrap:wrap;gap:8px')}>
            {works.map((w) => (
              <button key={w.slug} aria-pressed={w.slug === work} onClick={() => setWork(w.slug)} style={sx(CHIP, chip(w.slug === work))}>
                {WORK_SHORT[w.slug] || w.title}
              </button>
            ))}
          </div>
        </div>
        <div style={s('display:flex;flex-wrap:wrap;gap:12px')}>
          {(
            [
              ['Срочно', `В течение 2 часов, +${pct}%`, urgent, setUrgent],
              ['С выездом', fee ? `Мастер приедет к машине, +${rub(fee)}` : 'Мастер приедет к машине', onsite, setOnsite],
            ] as const
          ).map(([label, sub, on, set]) => (
            <button key={label} role="switch" aria-checked={on} onClick={() => set(!on)} style={s('flex:1 1 200px;min-height:56px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 16px;border-radius:13px;border:1px solid rgba(255,255,255,0.12);background:rgb(42,42,42);color:#fff;font-family:K2D,Jost,sans-serif;font-size:17px;cursor:pointer')}>
              <span style={s('display:flex;flex-direction:column;align-items:flex-start;gap:2px')}>
                <span>{label}</span>
                <span style={s('font-size:13px;color:rgb(150,150,150);text-align:left')}>{sub}</span>
              </span>
              <span style={sx('width:48px;height:28px;flex:none;border-radius:999px;position:relative;transition:background .2s', { background: on ? 'rgb(204,21,23)' : 'rgb(80,80,80)' })}>
                <span style={sx('position:absolute;top:3px;width:22px;height:22px;border-radius:50%;background:#fff;transition:left .2s', { left: on ? 23 : 3 })} />
              </span>
            </button>
          ))}
        </div>
      </div>
      <div style={s('flex:1 1 340px;min-width:0;border-radius:23px;padding:clamp(18px,2.4vw,32px);background:linear-gradient(214deg, rgb(0,0,0) 5%, rgb(102,102,102) 116%);display:flex;flex-direction:column;gap:16px')}>
        <span style={s('font-size:15px;color:rgb(184,184,184)')}>{summary}</span>
        <span aria-live="polite" style={sx('font-family:K2D,Jost,sans-serif;font-weight:100;font-size:clamp(52px,6vw,80px);line-height:1;transition:opacity .2s', { opacity: loading ? 0.55 : 1 })}>
          {total}
        </span>
        {calcErr && <span style={s('font-size:14px;color:rgb(255,107,107)')}>{calcErr}</span>}
        <button onClick={() => setBreakOpen(!breakOpen)} aria-expanded={breakOpen} style={s('align-self:flex-start;padding:0;border:0;background:transparent;color:#fff;font-family:K2D,Jost,sans-serif;font-size:16px;cursor:pointer;border-bottom:1px solid rgb(204,21,23);padding-bottom:4px')}>
          {breakOpen ? 'Скрыть расшифровку ▴' : 'Расшифровка ▾'}
        </button>
        {breakOpen && est && (
          <div style={s('display:flex;flex-direction:column;gap:0;border-radius:13px;background:rgba(0,0,0,0.35);padding:4px 14px')}>
            {est.breakdown.map((r, i) => (
              <div key={i} style={s('display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.08);font-size:15px')}>
                <span style={s('color:rgb(184,184,184)')}>{r.label}</span>
                <span style={s('white-space:nowrap')}>{i === 0 ? rub(r.amount) : `${r.amount < 0 ? '−' : '+'}${rub(Math.abs(r.amount))}`}</span>
              </div>
            ))}
          </div>
        )}
        <span style={s('font-size:13px;color:rgb(150,150,150);margin-top:auto')}>Цены условные, точную стоимость назовёт мастер</span>
        <button onClick={toForm} disabled={!est} className="hv-accent" style={s("min-height:56px;border-radius:13px;border:0;background:rgb(204,21,23);color:#fff;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:20px;cursor:pointer;padding:8px 16px")}>
          Оставить заявку с этим расчётом
        </button>
      </div>
    </div>
  );
}
