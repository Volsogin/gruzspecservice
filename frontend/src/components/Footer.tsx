import { Link } from 'react-router-dom';
import { s } from '../lib/css';
import { useContacts } from '../site';

const HEAD = "font-family:'Josefin Sans',Jost,sans-serif;font-weight:600;font-size:14px;letter-spacing:0.06em;color:#fff";
const CHIP = 'height:40px;padding:0 16px;border-radius:13px;background:rgb(42,42,42);display:flex;align-items:center';

export function Footer() {
  const c = useContacts();
  const r = c.requisites;
  const ids = [r.inn && `ИНН ${r.inn}`, r.kpp && `КПП ${r.kpp}`].filter(Boolean).join(' · ');
  return (
    <footer style={s('background:rgb(10,10,10);border-top:1px solid rgb(204,21,23);padding:56px clamp(16px,7.8vw,112px) max(40px, calc(150px - 8vw));display:flex;flex-direction:column;gap:40px;font-family:K2D,Jost,sans-serif;font-weight:300;font-size:16px;color:rgb(184,184,184)')}>
      <div style={s('display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:32px')}>
        <div style={s('display:flex;gap:14px;align-items:flex-start')}>
          <div style={s('width:60px;height:80px;flex:none;background:url(/assets/logo.webp) center / cover no-repeat')} />
          <div style={s('display:flex;flex-direction:column;gap:6px')}>
            <span style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:24px;color:#fff;line-height:1")}>ГрузСпецСервис</span>
            <span>Ремонт грузовиков, полуприцепов и спецтехники. Саратов и область.</span>
          </div>
        </div>
        <div style={s('display:flex;flex-direction:column;gap:8px')}>
          <span style={s(HEAD)}>КОНТАКТЫ</span>
          {c.address && <span>{c.address}</span>}
          {c.phoneHref && (
            <a href={c.phoneHref} style={s('font-size:20px;font-weight:400')}>
              {c.phoneDisplay}
            </a>
          )}
          {c.email && <a href={`mailto:${c.email}`}>{c.email}</a>}
          <span style={s('display:flex;align-items:center;gap:8px')}>
            <span style={s('width:7px;height:7px;border-radius:50%;background:oklch(0.72 0.17 150);flex:none')} />
            Круглосуточно, без выходных
          </span>
        </div>
        <div style={s('display:flex;flex-direction:column;gap:8px')}>
          <span style={s(HEAD)}>МЕССЕНДЖЕРЫ</span>
          <div style={s('display:flex;gap:8px;flex-wrap:wrap')}>
            {c.tgUrl && (
              <a href={c.tgUrl} target="_blank" rel="noopener" style={s(CHIP)}>
                Telegram
              </a>
            )}
            {c.maxUrl && (
              <a href={c.maxUrl} target="_blank" rel="noopener" style={s(CHIP)}>
                Max
              </a>
            )}
          </div>
          {c.botUrl && (
            <a href={c.botUrl} target="_blank" rel="noopener" style={s('height:44px;padding:0 16px;border-radius:13px;border:1px solid rgb(204,21,23);display:flex;align-items:center;justify-content:center;color:#fff;margin-top:4px')}>
              Написать в Telegram-бот
            </a>
          )}
        </div>
        <div style={s('display:flex;flex-direction:column;gap:8px;font-size:14px')}>
          <span style={s(HEAD)}>РЕКВИЗИТЫ</span>
          <span>{c.legalName}</span>
          {ids && <span>{ids}</span>}
          {r.ogrn && <span>ОГРН {r.ogrn}</span>}
          {r.vat && <span>{r.vat}</span>}
        </div>
      </div>
      <div style={s('display:flex;flex-wrap:wrap;gap:16px 32px;justify-content:space-between;padding-top:24px;border-top:1px solid rgba(255,255,255,0.08);font-size:14px')}>
        <span>© {new Date().getFullYear()} {c.legalName}</span>
        <Link to="/privacy" style={s('color:rgb(184,184,184);text-decoration:underline')}>
          Политика обработки персональных данных
        </Link>
      </div>
    </footer>
  );
}
