import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { s } from '../lib/css';
import { useContacts } from '../site';

export function NotFound() {
  const c = useContacts();
  useEffect(() => {
    document.title = 'Страница не найдена — ГрузСпецСервис';
  }, []);
  return (
    <main data-screen-label="404" style={s('flex:1;display:flex;align-items:center;justify-content:center;padding:clamp(40px,6vw,96px) 20px')}>
      <div style={s('display:flex;flex-direction:column;align-items:center;gap:22px;text-align:center;max-width:560px')}>
        <div aria-hidden="true" style={s('width:180px;height:154px;background:url(/assets/mascot-head.webp) center / contain no-repeat')} />
        <h1 style={s('margin:0;font-family:K2D,Jost,sans-serif;font-weight:100;font-size:clamp(96px,12vw,160px);line-height:0.9;color:rgb(204,21,23)')}>404</h1>
        <span style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:clamp(26px,2.6vw,36px);line-height:1.1;padding-bottom:16px;border-bottom:1px solid rgb(204,21,23)")}>Такой страницы нет</span>
        <span style={s('font-size:17px;color:rgb(184,184,184)')}>Возможно, ссылка устарела. Если машина стоит — звоните, ответим круглосуточно.</span>
        <div style={s('display:flex;flex-wrap:wrap;gap:10px;width:100%;max-width:440px')}>
          <a href={c.phoneHref} style={s("flex:1 1 180px;height:52px;border-radius:13px;background:rgb(204,21,23);display:flex;align-items:center;justify-content:center;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:19px;color:#fff")}>
            Позвонить
          </a>
          <Link to="/" style={s("flex:1 1 180px;height:52px;border-radius:13px;border:1px solid #fff;box-sizing:border-box;display:flex;align-items:center;justify-content:center;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:19px")}>
            На главную
          </Link>
        </div>
      </div>
    </main>
  );
}
