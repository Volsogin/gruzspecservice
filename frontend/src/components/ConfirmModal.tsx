import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { s, sx } from '../lib/css';
import { plural } from '../lib/format';
import { useWidth } from '../site';
import type { Submitted } from './RequestForm';

export function ConfirmModal({ data, onClose }: { data: Submitted; onClose: () => void }) {
  const m = useWidth() < 860;
  const { lead, email, calc } = data;
  const sm = lead.summary;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [onClose]);

  const rows: [string, string][] = [
    ['Тип', sm.type_label],
    ...(sm.vehicle_brand ? ([['Марка', sm.vehicle_brand]] as [string, string][]) : []),
    ['Адрес', sm.address || (sm.type === 'repair' ? 'На СТО' : '—')],
    ['Телефон', sm.phone_masked],
    ...(sm.type !== 'callback' ? ([['Фото', sm.photos_count ? `${sm.photos_count} шт.` : 'нет']] as [string, string][]) : []),
    ...(calc ? ([['Расчёт', calc]] as [string, string][]) : []),
  ];
  const mins = lead.callback_eta_minutes;

  return (
    <div onClick={onClose} style={sx('position:fixed;inset:0;z-index:90;display:flex;align-items:center;justify-content:center;overflow-y:auto', { background: m ? 'rgb(30,30,30)' : 'rgba(0,0,0,0.72)' })}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Заявка ${lead.number} отправлена`}
        onClick={(e) => e.stopPropagation()}
        style={sx('position:relative;width:100%;box-sizing:border-box;background:rgb(30,30,30);padding:clamp(24px,4vw,48px) clamp(18px,4vw,56px) calc(24px + env(safe-area-inset-bottom));display:flex;flex-direction:column;align-items:center;gap:22px;text-align:center', {
          maxWidth: m ? '100%' : 720,
          minHeight: m ? '100%' : 0,
          borderRadius: m ? 0 : 23,
        })}
      >
        <button onClick={onClose} aria-label="Закрыть" style={s('position:absolute;top:14px;right:14px;width:44px;height:44px;border-radius:13px;border:0;background:rgb(42,42,42);color:#fff;font-size:22px;cursor:pointer')}>
          ×
        </button>
        <span style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:200;font-size:clamp(34px,3.4vw,48px);line-height:1;padding:12px 24px 18px;border-bottom:1px solid rgb(204,21,23)")}>Отлично! Всё готово!</span>
        <div style={s('display:flex;flex-direction:column;align-items:center;gap:10px')}>
          <span style={s('font-family:K2D,Jost,sans-serif;font-weight:100;font-size:clamp(56px,6vw,80px);line-height:1;letter-spacing:0.02em')}>{lead.number}</span>
          <span style={s('display:flex;align-items:center;gap:8px;padding:6px 14px;border-radius:999px;background:oklch(0.72 0.12 240 / 0.16);border:1px solid oklch(0.72 0.12 240 / 0.6);font-size:15px')}>
            <span style={s('width:8px;height:8px;border-radius:50%;background:oklch(0.72 0.12 240)')} />
            {lead.status_label}
          </span>
        </div>
        <span style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:200;font-size:clamp(26px,2.4vw,34px);line-height:1.1")}>
          {sm.type === 'corporate' ? 'Менеджер свяжется' : 'Диспетчер перезвонит'} в течение {mins} {plural(mins, 'минуты', 'минут', 'минут')}
        </span>
        <div style={s('width:100%;max-width:520px;display:flex;flex-direction:column;border-radius:13px;background:rgb(24,24,24);padding:4px 16px;text-align:left')}>
          {rows.map(([k, v]) => (
            <div key={k} style={s('display:flex;justify-content:space-between;gap:16px;padding:11px 0;border-bottom:1px solid rgba(255,255,255,0.07);font-size:15px')}>
              <span style={s('color:rgb(150,150,150)')}>{k}</span>
              <span style={s('text-align:right')}>{v}</span>
            </div>
          ))}
        </div>
        <div style={s('width:100%;max-width:520px;display:flex;flex-wrap:wrap;gap:10px')}>
          <Link to={`/order/${lead.public_token}`} onClick={onClose} className="hv-accent" style={s("flex:1 1 220px;height:52px;border-radius:13px;background:rgb(204,21,23);display:flex;align-items:center;justify-content:center;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:19px;color:#fff")}>
            Открыть статус заявки
          </Link>
          {lead.telegram_bound ? (
            <span style={s("flex:1 1 220px;height:52px;border-radius:13px;border:1px solid rgba(255,255,255,0.2);box-sizing:border-box;display:flex;align-items:center;justify-content:center;gap:8px;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:19px")}>
              <span style={s('color:oklch(0.85 0.12 150)')}>✓</span>Написали вам в Telegram
            </span>
          ) : lead.telegram_bind_url && (
            <a href={lead.telegram_bind_url} target="_blank" rel="noopener" style={s("flex:1 1 220px;height:52px;border-radius:13px;border:1px solid #fff;box-sizing:border-box;display:flex;align-items:center;justify-content:center;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:19px")}>
              Получать статус в Telegram
            </a>
          )}
        </div>
        {email && <span style={s('font-size:14px;color:rgb(150,150,150)')}>Статусы придут и на e-mail {email}</span>}
        <span style={s('font-size:13px;color:rgb(128,128,128);max-width:480px')}>Сохраните ссылку на статус — по ней видно, что происходит с заявкой.</span>
      </div>
    </div>
  );
}
