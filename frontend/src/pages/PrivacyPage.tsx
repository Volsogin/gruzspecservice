import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { s } from '../lib/css';
import { fmtDate } from '../lib/format';
import { useContacts } from '../site';

interface Privacy {
  title: string;
  text: string;
  sections: { title: string; text: string }[];
  updated_at: string | null;
}

export function PrivacyPage() {
  const c = useContacts();
  const [p, setP] = useState<Privacy | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    document.title = 'Политика обработки персональных данных — ГрузСпецСервис';
    api<Privacy>('/legal/privacy').then(setP).catch(() => setErr(true));
  }, []);
  return (
    <main data-screen-label="Политика ПДн" style={s('flex:1;width:100%;max-width:760px;box-sizing:border-box;margin:0 auto;padding:clamp(32px,5vw,72px) 20px clamp(48px,6vw,96px);display:flex;flex-direction:column;gap:28px')}>
      <h1 style={s("margin:0;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:clamp(34px,4vw,52px);line-height:1.05;padding-bottom:16px;border-bottom:1px solid rgb(204,21,23)")}>
        {p?.title || 'Политика обработки персональных данных'}
      </h1>
      <span style={s('font-size:15px;color:rgb(150,150,150)')}>
        {p?.updated_at ? `Редакция от ${fmtDate(p.updated_at)} · ` : ''}
        {c.legalName}
        {c.requisites.inn ? `, ИНН ${c.requisites.inn}` : ''}
      </span>
      {err && <p style={s('margin:0;font-size:17px;color:rgb(184,184,184)')}>Не удалось загрузить текст. Обновите страницу или напишите нам: {c.email}</p>}
      {p && p.sections.length === 0 && <p style={s('margin:0;font-weight:300;font-size:17px;line-height:1.6;color:rgb(214,214,214);white-space:pre-line')}>{p.text}</p>}
      {p?.sections.map((sec) => (
        <section key={sec.title} style={s('display:flex;flex-direction:column;gap:10px')}>
          <h2 style={s("margin:0;font-family:'Josefin Sans',Jost,sans-serif;font-weight:600;font-size:19px;letter-spacing:0.02em")}>{sec.title}</h2>
          <p style={s('margin:0;font-weight:300;font-size:17px;line-height:1.6;color:rgb(214,214,214);text-wrap:pretty')}>{sec.text}</p>
        </section>
      ))}
    </main>
  );
}
