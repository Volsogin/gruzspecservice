import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError, type OrderOut } from '../lib/api';
import { s, sx } from '../lib/css';
import { fmtDateTime, fmtTime, rub } from '../lib/format';
import { softColor, STATUS_COLOR, VEHICLE_SHORT } from '../lib/labels';
import { useContacts, useWidth } from '../site';

const SHORT_LABEL: Record<string, string> = { on_the_way: 'Мастер выехал' };
const POLL_MS = 30_000;

function Skeleton() {
  const sk = (h: number, w: string | number = '100%') => <div style={{ height: h, width: w, borderRadius: 23, background: 'rgb(30,30,30)', animation: 'gspulse 1.2s ease-in-out infinite' }} />;
  return (
    <div style={s('display:flex;flex-direction:column;gap:20px')} aria-busy="true" aria-label="Загружаем заявку">
      {sk(24, 220)}
      {sk(80, 320)}
      {sk(120)}
      <div style={s('display:flex;gap:20px;flex-wrap:wrap')}>
        {sk(320, 'min(100%, 560px)')}
        {sk(320, 'min(100%, 400px)')}
      </div>
    </div>
  );
}

export function OrderPage() {
  const { token = '' } = useParams();
  const m = useWidth() < 860;
  const c = useContacts();
  const [order, setOrder] = useState<OrderOut | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'notfound' | 'error'>('loading');
  const [tgPending, setTgPending] = useState(false);
  const timer = useRef<number>();

  const load = (quiet = false) => {
    if (!quiet) setState((st) => (st === 'ready' ? st : 'loading'));
    return api<OrderOut>(`/orders/${encodeURIComponent(token)}`)
      .then((o) => {
        setOrder(o);
        setState('ready');
        return o;
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setState('notfound');
        else if (!quiet) setState('error');
        return null;
      });
  };

  useEffect(() => {
    void load();
    const poll = () => {
      if (document.visibilityState === 'visible') void load(true);
    };
    timer.current = window.setInterval(poll, POLL_MS);
    document.addEventListener('visibilitychange', poll);
    return () => {
      window.clearInterval(timer.current);
      document.removeEventListener('visibilitychange', poll);
    };
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (order) document.title = `Заявка ${order.number} — ГрузСпецСервис`;
  }, [order?.number]); // eslint-disable-line react-hooks/exhaustive-deps

  // After «Получать статус в Telegram» poll faster for a minute to flip the badge.
  useEffect(() => {
    if (!tgPending) return;
    let n = 0;
    const id = window.setInterval(async () => {
      n++;
      const o = await load(true);
      if (o?.telegram_bound || n > 20) {
        setTgPending(false);
        window.clearInterval(id);
      }
    }, 3000);
    return () => window.clearInterval(id);
  }, [tgPending]); // eslint-disable-line react-hooks/exhaustive-deps

  const main = (children: React.ReactNode) => (
    <main data-screen-label="Страница заказа" style={s('flex:1;width:100%;max-width:1203px;box-sizing:border-box;margin:0 auto;padding:clamp(24px,4vw,56px) clamp(16px,3vw,24px) clamp(48px,6vw,96px);display:flex;flex-direction:column;gap:28px')}>
      {children}
    </main>
  );

  if (state === 'loading') return main(<Skeleton />);
  if (state === 'notfound' || state === 'error' || !order) {
    const nf = state === 'notfound';
    return main(
      <div style={s('align-self:center;width:100%;max-width:640px;box-sizing:border-box;margin-top:clamp(0px,4vw,48px);background:rgb(30,30,30);border-radius:23px;padding:clamp(28px,4vw,56px) clamp(20px,4vw,48px);display:flex;flex-direction:column;align-items:center;gap:20px;text-align:center')}>
        <h1 style={s("margin:0;font-family:'Josefin Sans',Jost,sans-serif;font-weight:100;font-size:clamp(32px,3.4vw,44px);line-height:1.05;padding:0 16px 16px;border-bottom:1px solid rgb(204,21,23)")}>{nf ? 'Заявка не найдена — проверьте ссылку' : 'Не удалось загрузить заявку'}</h1>
        <span style={s('font-size:17px;color:rgb(184,184,184);max-width:440px')}>
          {nf ? 'Скопируйте ссылку из письма или Telegram целиком или позвоните — найдём заявку по телефону.' : 'Проверьте интернет и обновите страницу. Если машина стоит — звоните, ответим круглосуточно.'}
        </span>
        <div style={s('display:flex;flex-wrap:wrap;gap:10px;width:100%;max-width:440px')}>
          <a href={c.phoneHref} style={s("flex:1 1 180px;height:52px;border-radius:13px;background:rgb(204,21,23);display:flex;align-items:center;justify-content:center;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:19px;color:#fff")}>
            Позвонить
          </a>
          {nf ? (
            <Link to="/" style={s("flex:1 1 180px;height:52px;border-radius:13px;border:1px solid #fff;box-sizing:border-box;display:flex;align-items:center;justify-content:center;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:19px")}>
              На главную
            </Link>
          ) : (
            <button onClick={() => void load()} style={s("flex:1 1 180px;height:52px;border-radius:13px;border:1px solid #fff;background:transparent;color:#fff;box-sizing:border-box;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:19px;cursor:pointer")}>
              Повторить
            </button>
          )}
        </div>
      </div>,
    );
  }

  const sm = order.summary;
  const color = STATUS_COLOR[order.status] || STATUS_COLOR.new;
  const done = order.status === 'completed';
  const reachedAt: Record<string, string> = {};
  for (const h of order.history) reachedAt[h.status] = h.at;
  const lastAt = order.history.length ? order.history[order.history.length - 1].at : order.updated_at;
  const since = done ? `завершена в ${fmtTime(lastAt)}` : `с ${fmtTime(reachedAt[order.status] || order.updated_at)}`;
  const kind = sm.type === 'onsite' ? 'выезд мастера' : sm.type === 'tow' ? 'эвакуатор' : sm.type_label.toLowerCase();

  const rows: [string, string][] = [['Тип', sm.type_label]];
  if (sm.vehicle_brand) rows.push(['Марка', sm.vehicle_brand]);
  if (sm.vehicle_type) rows.push(['Тип техники', VEHICLE_SHORT[sm.vehicle_type] || sm.vehicle_type_label || sm.vehicle_type]);
  for (const d of sm.details) rows.push([d.label.replace(/\?$/, ''), d.value]);
  if (sm.description) rows.push([sm.type === 'parts' ? 'Деталь' : 'Что случилось', sm.description]);
  if (sm.address) rows.push(['Адрес', sm.address]);
  rows.push(['Телефон', sm.phone_masked]);

  const est = sm.estimate;
  const estTitle = est?.input ? `Расчёт калькулятора${est.input.onsite ? ' · с выездом' : ''}${est.input.urgent ? ' · срочно' : ''}` : 'Расчёт калькулятора';

  return main(
    <>
      <div style={s('display:flex;flex-wrap:wrap;gap:20px;align-items:flex-end;justify-content:space-between')}>
        <div style={s('display:flex;flex-direction:column;gap:12px')}>
          <span style={s('font-size:14px;color:rgb(150,150,150)')}>
            Заявка · {kind} · от {fmtDateTime(order.created_at)}
          </span>
          <h1 style={s('margin:0;font-family:K2D,Jost,sans-serif;font-weight:100;font-size:clamp(56px,6vw,88px);line-height:0.95')}>{order.number}</h1>
          <div style={s('display:flex;flex-wrap:wrap;align-items:center;gap:14px')}>
            <span style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:clamp(28px,3vw,44px);line-height:1")}>{order.status_label}</span>
            <span style={sx('display:flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;border:1px solid;font-size:14px', { background: softColor(color), borderColor: color })}>
              <span style={sx('width:8px;height:8px;border-radius:50%', { background: color })} />
              {since}
            </span>
          </div>
        </div>
        <div style={s('display:flex;flex-wrap:wrap;gap:10px')}>
          {order.telegram_bound ? (
            <span style={s('height:52px;padding:0 18px;border-radius:13px;background:oklch(0.72 0.17 150 / 0.14);border:1px solid oklch(0.72 0.17 150 / 0.6);box-sizing:border-box;display:flex;align-items:center;gap:8px;font-size:16px')}>
              <span style={s('color:oklch(0.85 0.12 150)')}>✓</span>Telegram подключён
            </span>
          ) : order.telegram_bind_url ? (
            <a href={order.telegram_bind_url} target="_blank" rel="noopener" onClick={() => setTgPending(true)} className="hv-bd-accent" style={s("height:52px;padding:0 20px;border-radius:13px;border:1px solid #fff;background:transparent;color:#fff;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:19px;display:flex;align-items:center;box-sizing:border-box")}>
              {tgPending ? 'Ждём «Start» в боте…' : 'Получать статус в Telegram'}
            </a>
          ) : null}
          <a href={c.phoneHref} className="hv-accent" style={s("height:52px;padding:0 24px;border-radius:13px;background:rgb(204,21,23);display:flex;align-items:center;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:19px;color:#fff")}>
            Позвонить
          </a>
        </div>
      </div>

      {order.is_cancelled && (
        <div style={s('display:flex;flex-direction:column;gap:6px;padding:18px 20px;border-radius:13px;background:rgb(30,30,30);border:1px solid rgba(255,255,255,0.18)')}>
          <span style={s('font-size:18px')}>Заявка отменена</span>
          <span style={s('font-size:15px;color:rgb(184,184,184)')}>
            {order.history.find((h) => h.status === 'cancelled')?.comment ? `${order.history.find((h) => h.status === 'cancelled')!.comment}. ` : ''}Если это ошибка — позвоните, восстановим заявку.
          </span>
        </div>
      )}

      <ol aria-label="Этапы заявки" style={sx('margin:0;list-style:none;display:flex;padding:clamp(18px,2.4vw,28px);border-radius:23px;background:rgb(30,30,30)', { flexDirection: m ? 'column' : 'row', gap: m ? 0 : 8, opacity: order.is_cancelled ? 0.55 : 1 })}>
        {order.steps.map((st, i) => {
          const isDone = !order.is_cancelled && st.done && (!st.current || done);
          const now = !order.is_cancelled && st.current && !done;
          const last = i === order.steps.length - 1;
          const accent = done ? STATUS_COLOR.completed : 'rgb(204,21,23)';
          return (
            <li key={st.status} aria-current={now ? 'step' : undefined} style={sx('flex:1;display:flex;gap:12px;min-width:0', { flexDirection: m ? 'row' : 'column' })}>
              <div style={sx('display:flex;align-items:center;gap:0', { flexDirection: m ? 'column' : 'row' })}>
                <span style={sx('width:28px;height:28px;flex:none;border-radius:50%;box-sizing:border-box;border:2px solid;display:flex;align-items:center;justify-content:center;font-size:13px;color:#fff', { borderColor: isDone || now ? accent : 'rgba(255,255,255,0.2)', background: isDone ? accent : now ? 'rgba(204,21,23,0.25)' : 'transparent' })}>
                  {isDone ? '✓' : ''}
                </span>
                <span style={{ flex: 1, minWidth: m ? 0 : 12, minHeight: m ? 16 : 0, height: m ? 'auto' : 2, width: m ? 2 : 'auto', background: last ? 'transparent' : isDone && !st.current ? accent : 'rgba(255,255,255,0.14)' }} />
              </div>
              <div style={sx('display:flex;flex-direction:column;gap:4px', { paddingBottom: m && !last ? 20 : 0 })}>
                <span style={sx('font-size:16px;line-height:1.2', { color: isDone || now ? '#fff' : 'rgb(150,150,150)' })}>{SHORT_LABEL[st.status] || st.label}</span>
                <span style={s('font-size:13px;color:rgb(150,150,150)')}>{reachedAt[st.status] ? fmtTime(reachedAt[st.status]) : '—'}</span>
              </div>
            </li>
          );
        })}
      </ol>

      <div style={s('display:flex;flex-wrap:wrap;gap:20px;align-items:flex-start')}>
        <div style={s('flex:1 1 420px;min-width:0;display:flex;flex-direction:column;gap:16px;padding:clamp(18px,2.4vw,28px);border-radius:23px;background:rgb(30,30,30)')}>
          <h2 style={s("margin:0;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:26px")}>История</h2>
          <div style={s('display:flex;flex-direction:column')}>
            {order.history
              .slice()
              .reverse()
              .map((h, i) => (
                <div key={i} style={s('display:flex;gap:14px')}>
                  <div style={s('display:flex;flex-direction:column;align-items:center;width:12px;flex:none')}>
                    <span style={sx('width:10px;height:10px;border-radius:50%;margin-top:6px', { background: STATUS_COLOR[h.status] || STATUS_COLOR.new })} />
                    <span style={s('flex:1;width:1px;background:rgba(255,255,255,0.12)')} />
                  </div>
                  <div style={s('display:flex;flex-direction:column;gap:4px;padding-bottom:20px')}>
                    <span style={s('display:flex;gap:10px;align-items:baseline;flex-wrap:wrap')}>
                      <span style={s('font-size:17px')}>{h.label}</span>
                      <span style={s('font-size:13px;color:rgb(150,150,150)')}>{fmtDateTime(h.at)}</span>
                    </span>
                    {h.comment && <span style={s('font-size:15px;color:rgb(184,184,184);line-height:1.4')}>{h.comment}</span>}
                    {!h.comment && h.status === 'new' && (
                      <span style={s('font-size:15px;color:rgb(184,184,184);line-height:1.4')}>
                        Заявка с сайта{sm.photos_count ? `, ${sm.photos_count} фото` : ''}. Перезвоним в течение {order.callback_eta_minutes} минут.
                      </span>
                    )}
                  </div>
                </div>
              ))}
          </div>
        </div>
        <div style={s('flex:1 1 380px;min-width:0;display:flex;flex-direction:column;gap:20px')}>
          <div style={s('display:flex;flex-direction:column;padding:clamp(18px,2.4vw,28px);border-radius:23px;background:rgb(30,30,30)')}>
            <h2 style={s("margin:0;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:26px;padding-bottom:8px")}>Сводка</h2>
            {rows.map(([k, v], i) => (
              <div key={i} style={s('display:flex;justify-content:space-between;gap:16px;padding:11px 0;border-bottom:1px solid rgba(255,255,255,0.07);font-size:15px')}>
                <span style={s('color:rgb(150,150,150);flex:none')}>{k}</span>
                <span style={s('text-align:right;overflow-wrap:anywhere')}>{v}</span>
              </div>
            ))}
            {sm.photos.length > 0 && (
              <div style={s('display:flex;flex-direction:column;gap:10px;padding-top:16px')}>
                <span style={s('font-size:14px;color:rgb(150,150,150)')}>Фото · {sm.photos.length}</span>
                <div style={s('display:flex;gap:10px;flex-wrap:wrap')}>
                  {sm.photos.map((p, i) => (
                    <a key={i} href={p.url} target="_blank" rel="noopener" aria-label={`Фото ${i + 1}`} style={sx('width:96px;height:96px;border-radius:13px', { background: `rgb(42,42,42) url(${p.preview_url}) center / cover no-repeat` })} />
                  ))}
                </div>
              </div>
            )}
          </div>
          {est && (
            <div style={s('display:flex;flex-direction:column;gap:10px;padding:clamp(18px,2.4vw,28px);border-radius:23px;background:linear-gradient(214deg, rgb(0,0,0) 5%, rgb(102,102,102) 116%)')}>
              <span style={s('font-size:14px;color:rgb(184,184,184)')}>{estTitle}</span>
              <span style={s('font-weight:100;font-size:56px;line-height:1')}>{est.price_label || `от ${rub(est.price_from)}`}</span>
              {est.breakdown && (
                <div style={s('display:flex;flex-direction:column;font-size:14px')}>
                  {est.breakdown.map((r, i) => (
                    <div key={i} style={s('display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.08)')}>
                      <span style={s('color:rgb(184,184,184)')}>{r.label}</span>
                      <span style={s('white-space:nowrap')}>{i === 0 ? rub(r.amount) : `+${rub(r.amount)}`}</span>
                    </div>
                  ))}
                </div>
              )}
              <span style={s('font-size:12px;color:rgb(150,150,150)')}>Цены условные, точную стоимость назовёт мастер</span>
            </div>
          )}
          <span style={s('font-size:13px;color:rgb(128,128,128)')}>Страница обновляется сама. {order.email_notifications ? 'Статусы приходят и на e-mail.' : ''}</span>
        </div>
      </div>
    </>,
  );
}
