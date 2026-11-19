import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { s } from '../lib/css';
import { openChat, openForm } from '../lib/bus';
import { useContacts, useWidth } from '../site';

const NAV: [string, string][] = [
  ['Услуги', 'services'],
  ['Цены', 'prices'],
  ['Выезд', 'zone'],
  ['Отзывы', 'reviews'],
  ['Контакты', 'contacts'],
];

const ROUND_ICON =
  'width:40px;height:40px;border-radius:50%;background:rgb(42,42,42);display:flex;align-items:center;justify-content:center;font-family:K2D,Jost,sans-serif;font-weight:600;font-size:12px';

export function Header() {
  const w = useWidth();
  const m = w < 1100;
  const [menu, setMenu] = useState(false);
  const c = useContacts();
  const navigate = useNavigate();

  useEffect(() => {
    document.body.style.overflow = menu ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [menu]);

  const callMaster = () => openForm({ type: 'visit' }, navigate);

  if (!m) {
    return (
      <header style={s('height:111px;display:flex;align-items:center;gap:clamp(12px,2.2vw,32px);padding:0 24px 0 0;background:rgb(18,18,18);border-bottom:1px solid rgba(255,255,255,0.08);box-sizing:border-box')}>
        <Link to="/" aria-label="ГрузСпецСервис — на главную" style={s('display:block;width:83px;height:111px;flex:none;background:url(/assets/logo.webp) center / cover no-repeat')} />
        <nav aria-label="Разделы" style={s('display:flex;gap:clamp(10px,1.9vw,28px);flex:1;justify-content:center;min-width:0')}>
          {NAV.map(([label, id]) => (
            <Link key={id} to={'/#' + id} className="hv-red" style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:20px;color:#fff;padding:0 clamp(4px,1.2vw,18px) 8px;white-space:nowrap;border-bottom:1px solid rgb(204,21,23);line-height:1")}>
              {label}
            </Link>
          ))}
        </nav>
        <div style={s('display:flex;align-items:center;gap:12px;flex:none')}>
          <div style={s('display:flex;align-items:center;gap:8px;font-family:K2D,Jost,sans-serif;font-weight:300;font-size:14px;color:rgb(184,184,184)')}>
            <span style={s('width:8px;height:8px;border-radius:50%;background:oklch(0.72 0.17 150);box-shadow:0 0 0 4px oklch(0.72 0.17 150 / 0.18)')} />
            <span>{w >= 1300 ? c.statusLabel : '24/7'}</span>
          </div>
          {c.tgUrl && (
            <a href={c.tgUrl} target="_blank" rel="noopener" title="Telegram" className="hv-s3" style={s(ROUND_ICON)}>
              TG
            </a>
          )}
          {c.maxUrl && (
            <a href={c.maxUrl} target="_blank" rel="noopener" title="Max" className="hv-s3" style={{ ...s(ROUND_ICON), fontSize: 11 }}>
              MAX
            </a>
          )}
          <a href={c.phoneHref} className="hv-accent" style={s('height:40px;padding:0 18px;border-radius:13px;background:rgb(204,21,23);display:flex;align-items:center;gap:10px;font-family:K2D,Jost,sans-serif;font-weight:400;font-size:18px;color:#fff;white-space:nowrap')}>
            <span style={s('width:18px;height:18px;background:url(/assets/icon-a.webp) center / contain no-repeat;filter:invert(1)')} />
            <span>{c.phoneDisplay || 'Позвонить'}</span>
          </a>
        </div>
      </header>
    );
  }

  return (
    <>
      <header style={s('position:sticky;top:0;z-index:40;height:64px;display:flex;align-items:center;gap:8px;padding:0 12px 0 4px;background:rgba(18,18,18,0.94);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border-bottom:1px solid rgba(255,255,255,0.08)')}>
        <Link to="/" aria-label="На главную" onClick={() => setMenu(false)} style={s('display:block;width:45px;height:60px;flex:none;background:url(/assets/logo.webp) center / cover no-repeat')} />
        <div style={s('display:flex;flex-direction:column;gap:2px;flex:1;min-width:0')}>
          <span style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:17px;line-height:1")}>ГрузСпецСервис</span>
          <span style={s('display:flex;align-items:center;gap:6px;font-family:K2D,Jost,sans-serif;font-weight:300;font-size:12px;color:rgb(184,184,184)')}>
            <span style={s('width:7px;height:7px;border-radius:50%;background:oklch(0.72 0.17 150)')} />
            {c.statusLabel}
          </span>
        </div>
        <a href={c.phoneHref} aria-label="Позвонить" style={s('width:44px;height:44px;border-radius:13px;background:rgb(204,21,23);display:flex;align-items:center;justify-content:center')}>
          <span style={s('width:20px;height:20px;background:url(/assets/icon-a.webp) center / contain no-repeat;filter:invert(1)')} />
        </a>
        <button onClick={() => setMenu((v) => !v)} aria-label={menu ? 'Закрыть меню' : 'Меню'} aria-expanded={menu} style={s('width:44px;height:44px;border-radius:13px;background:rgb(42,42,42);border:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;cursor:pointer')}>
          <span style={s('width:20px;height:1.5px;background:#fff')} />
          <span style={s('width:20px;height:1.5px;background:#fff')} />
          <span style={s('width:20px;height:1.5px;background:#fff')} />
        </button>
      </header>
      {menu && (
        <div style={s('position:fixed;inset:64px 0 0 0;z-index:39;background:rgb(18,18,18);padding:24px 20px 120px;display:flex;flex-direction:column;gap:8px;overflow:auto')}>
          {NAV.map(([label, id]) => (
            <Link key={id} to={'/#' + id} onClick={() => setMenu(false)} style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:32px;padding:14px 0;border-bottom:1px solid rgb(204,21,23)")}>
              {label}
            </Link>
          ))}
          <div style={s('display:flex;gap:12px;margin-top:24px')}>
            {c.tgUrl && (
              <a href={c.tgUrl} target="_blank" rel="noopener" style={s('flex:1;height:52px;border-radius:13px;background:rgb(42,42,42);display:flex;align-items:center;justify-content:center;font-family:K2D,Jost,sans-serif;font-size:16px')}>
                Telegram
              </a>
            )}
            {c.maxUrl && (
              <a href={c.maxUrl} target="_blank" rel="noopener" style={s('flex:1;height:52px;border-radius:13px;background:rgb(42,42,42);display:flex;align-items:center;justify-content:center;font-family:K2D,Jost,sans-serif;font-size:16px')}>
                Max
              </a>
            )}
          </div>
          <a href={c.phoneHref} style={s('height:52px;border-radius:13px;background:rgb(204,21,23);display:flex;align-items:center;justify-content:center;font-family:K2D,Jost,sans-serif;font-size:18px')}>
            {c.phoneDisplay || 'Позвонить'}
          </a>
        </div>
      )}
      <nav aria-label="Быстрые действия" style={s('position:fixed;left:0;right:0;bottom:0;z-index:45;display:grid;grid-template-columns:1fr 1.5fr 1fr;gap:8px;padding:8px 10px calc(8px + env(safe-area-inset-bottom));background:rgba(18,18,18,0.96);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border-top:1px solid rgba(255,255,255,0.1)')}>
        <a href={c.phoneHref} style={s('height:52px;border-radius:13px;background:rgb(42,42,42);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;font-family:K2D,Jost,sans-serif;font-size:13px')}>
          <span style={s('width:18px;height:18px;background:url(/assets/icon-a.webp) center / contain no-repeat;filter:invert(1)')} />
          Позвонить
        </a>
        <button onClick={() => { setMenu(false); callMaster(); }} style={s("height:52px;border-radius:13px;background:rgb(204,21,23);border:0;color:#fff;font-family:'Josefin Sans',Jost,sans-serif;font-weight:400;font-size:17px;cursor:pointer")}>
          Вызвать мастера
        </button>
        <button onClick={() => { setMenu(false); openChat(); }} style={s('height:52px;border-radius:13px;background:rgb(42,42,42);border:0;color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;font-family:K2D,Jost,sans-serif;font-size:13px;cursor:pointer;position:relative')}>
          <span style={s('width:24px;height:24px;border-radius:50%;background:rgb(204,21,23) url(/assets/mascot-head.webp) center 40% / 125% no-repeat')} />
          Чат
        </button>
      </nav>
    </>
  );
}
