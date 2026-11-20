import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Calculator } from '../components/Calculator';
import { ConfirmModal } from '../components/ConfirmModal';
import { DgisMap } from '../components/DgisMap';
import { MapZone } from '../components/MapZone';
import { RequestForm, type Submitted } from '../components/RequestForm';
import { api, type CaseOut, type Review } from '../lib/api';
import { homeState, openForm, uiType } from '../lib/bus';
import { H2, s, sx } from '../lib/css';
import { fmtDate, num, plural, rub, stars } from '../lib/format';
import { SERVICE_ICON, SERVICE_PROBLEM, SOURCE_SHORT } from '../lib/labels';
import { useContacts, useSite, useWidth } from '../site';

const CORP_POINTS = ['Договор и счёт с НДС', 'Закрывающие документы сразу', 'Отсрочка платежа до 10 дней', 'Приоритетный выезд для парка', 'Один менеджер на все машины'];
const BRANDS_FALLBACK = ['MAN', 'Scania', 'Volvo', 'DAF', 'Mercedes-Benz', 'Iveco', 'Renault', 'Sitrak', 'Shacman', 'Howo', 'FAW', 'Foton', 'Dongfeng', 'КамАЗ', 'МАЗ', 'ГАЗон Next', 'Урал Next', 'Schmitz', 'Krone', 'Kögel'];

function avg(n: number): string {
  return (Math.round(n * 10) / 10).toFixed(1);
}

function hours(h: number | null): string {
  if (h == null) return '—';
  if (h < 1) return `${Math.round(h * 60)} мин`;
  const whole = Math.floor(h);
  const mins = Math.round((h - whole) * 60);
  return mins ? `${whole} ч ${mins} мин` : `${whole} ${plural(whole, 'час', 'часа', 'часов')}`;
}

export function Home() {
  const w = useWidth();
  const m = w < 860;
  const location = useLocation();
  const { data } = useSite();
  const c = useContacts();
  const ribbonRef = useRef<HTMLDivElement>(null);
  const [confirm, setConfirm] = useState<Submitted | null>(null);

  useEffect(() => {
    homeState.mounted = true;
    return () => {
      homeState.mounted = false;
    };
  }, []);

  // Header links are "/#id": scroll once the section exists (also after data loads).
  useEffect(() => {
    const id = location.hash.slice(1);
    if (!id || (id === 'form' && homeState.pending)) return;
    const t = setTimeout(() => {
      const el = document.getElementById(id);
      if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (m ? 70 : 10), behavior: 'smooth' });
    }, 60);
    return () => clearTimeout(t);
  }, [location.key, !!data]); // eslint-disable-line react-hooks/exhaustive-deps

  const settings = data?.settings;
  const services = data?.services || [];
  const rating = data?.reviews.summary.average_rating;
  const scrollRib = (dir: number) => ribbonRef.current?.scrollBy({ left: dir * 316 * 2, behavior: 'smooth' });

  const advantages = (settings?.advantages || []).map((a, i) => ({ t: a.title.toUpperCase(), d: a.text, n: i + 1 }));
  const stats = (settings?.stats.items || []).map((x) => ({ n: `${num(x.value)}${x.suffix}`, l: x.label }));
  const brandsLine = data?.brands.length ? data.brands.map((b) => b.title) : BRANDS_FALLBACK;
  const twoGisFirm = settings?.review_links['2gis']?.replace(/\/tab\/reviews\/?$/, '') || 'https://2gis.ru/saratov';
  const center = data?.dispatch_zone.center || { lat: 51.607788, lon: 45.923923 };

  return (
    <>
      <section data-screen-label="Первый экран" style={s('position:relative;background:url(/assets/hero-bg.webp) center / cover no-repeat')}>
        <div style={s('position:absolute;inset:0;background:linear-gradient(244.6deg, rgba(0,0,0,0.2) 22.6%, rgba(102,102,102,0.2) 96.9%), linear-gradient(rgba(30,30,30,0.8),rgba(30,30,30,0.8))')} />
        <div style={s('position:relative;display:flex;flex-wrap:wrap;gap:28px;padding:clamp(20px,2vw,28px) clamp(16px,1.7vw,24px) clamp(28px,3vw,40px)')}>
          <div style={s('flex:1 1 360px;max-width:440px;display:flex;flex-direction:column;gap:18px')}>
            <span style={s('font-family:K2D,Jost,sans-serif;font-weight:500;font-size:clamp(44px,4.45vw,64px);line-height:1')}>ГрузСпецСервис Автосервис</span>
            <h1 style={s("margin:0;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:clamp(20px,1.7vw,24px);line-height:1.2;text-wrap:pretty")}>Ремонт грузовиков и спецтехники 24/7 — на СТО и с выездом к месту поломки</h1>
            <div style={s('display:flex;flex-wrap:wrap;gap:10px')}>
              {rating ? (
                <a href="#reviews" style={s('height:40px;padding:0 14px;border-radius:13px;background:rgb(204,21,23);display:flex;align-items:center;gap:8px;font-family:K2D,Jost,sans-serif;font-weight:200;font-size:28px;line-height:1;color:#fff')}>
                  <span style={s('color:rgb(255,136,0);font-size:24px')}>★</span>
                  {avg(rating)} – наш рейтинг
                </a>
              ) : null}
              <span style={s('height:40px;padding:0 14px;border-radius:13px;border:1px solid rgba(255,255,255,0.7);display:flex;align-items:center;gap:8px;font-family:K2D,Jost,sans-serif;font-weight:300;font-size:16px;box-sizing:border-box')}>
                <span style={s('width:8px;height:8px;border-radius:50%;background:oklch(0.72 0.17 150)')} />
                Выезд за {settings?.dispatch.eta_minutes || 30} минут по городу
              </span>
            </div>
            <div style={s('display:flex;flex-wrap:wrap;gap:10px;margin-top:4px')}>
              <button onClick={() => openForm({ type: 'visit' })} className="hv-accent" style={s("flex:1 1 180px;height:52px;border-radius:13px;border:0;background:rgb(204,21,23);color:#fff;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:21px;cursor:pointer")}>
                Вызвать мастера
              </button>
              <button onClick={() => openForm({ type: 'sto' })} className="hv-white10" style={s("flex:1 1 180px;min-height:52px;border-radius:13px;border:1px solid #fff;background:rgba(0,0,0,0.25);color:#fff;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:21px;cursor:pointer;padding:4px 12px")}>
                Записаться на ремонт
              </button>
            </div>
            <a href="#services" style={s("align-self:flex-start;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:24px;line-height:1.05;padding-bottom:12px;border-bottom:1px solid rgb(204,21,23);width:319px;max-width:100%;color:#fff")}>
              Наши услуги в<br />
              СТО / на выезде
            </a>
          </div>
          {!m ? (
            <div style={s('flex:1 1 640px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:27px;align-content:end')}>
              <div style={s('grid-column:2;aspect-ratio:306/177;border-radius:23px;background:url(/assets/hero-1.webp) center / cover no-repeat')} />
              <div style={s('grid-column:1;aspect-ratio:306/175;border-radius:23px;background:url(/assets/hero-2.webp) center / cover no-repeat')} />
              <div style={s('aspect-ratio:306/175;border-radius:23px;background:rgb(204,21,23);padding:15px 17px;box-sizing:border-box;font-family:K2D,Jost,sans-serif;font-weight:300;font-size:clamp(15px,1.4vw,20px);line-height:1.1;overflow:hidden')}>
                Опытные мастера и много лет в грузовом сервисе — поэтому даём гарантию на работы.
              </div>
              <div style={s('aspect-ratio:306/175;border-radius:23px;background:url(/assets/hero-3.webp) center / cover no-repeat')} />
            </div>
          ) : (
            <div style={s('display:grid;grid-template-columns:1fr 1fr;gap:12px;width:100%')}>
              <div style={s('grid-column:1 / 3;aspect-ratio:16/9;border-radius:23px;background:url(/assets/hero-1.webp) center / cover no-repeat')} />
              <div style={s('aspect-ratio:1;border-radius:23px;background:url(/assets/hero-3.webp) center / cover no-repeat')} />
              <div style={s('border-radius:23px;background:rgb(204,21,23);padding:14px;font-family:K2D,Jost,sans-serif;font-weight:300;font-size:14px;line-height:1.15')}>
                Опытные мастера и много лет в грузовом сервисе — поэтому даём гарантию на работы.
              </div>
            </div>
          )}
        </div>
      </section>

      <section id="services" data-screen-label="Лента услуг" style={s('position:relative;padding:28px 0 32px;border-bottom:1px solid rgba(255,255,255,0.14)')}>
        <h2 className="sr-only">Услуги</h2>
        <div style={s('display:flex;align-items:center;gap:12px;padding:0 clamp(16px,1.7vw,24px)')}>
          {!m && (
            <button onClick={() => scrollRib(-1)} aria-label="Назад" className="hv-bd-accent" style={s('width:52px;height:52px;flex:none;border-radius:50%;border:1px solid rgba(255,255,255,0.3);background:transparent;color:#fff;font-size:22px;cursor:pointer')}>
              ←
            </button>
          )}
          <div ref={ribbonRef} style={s('flex:1;min-width:0;display:flex;gap:16px;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none;padding:4px 2px 8px')}>
            {(services.length ? services : Array.from({ length: 5 }, () => null)).map((sv, i) =>
              sv ? (
                <button
                  key={sv.slug}
                  onClick={() => openForm({ type: uiType(sv.form_type), serviceSlug: sv.slug, problem: SERVICE_PROBLEM[sv.slug] })}
                  className="hv-ring"
                  style={s('flex:none;width:clamp(270px,21vw,300px);scroll-snap-align:start;text-align:left;display:flex;flex-direction:column;gap:12px;padding:22px;border-radius:23px;border:0;background:linear-gradient(214deg, rgb(0,0,0) 5%, rgb(102,102,102) 116%);color:#fff;cursor:pointer;box-shadow:inset 0 0 0 1px rgba(255,255,255,0.06)')}
                >
                  <div style={s('display:flex;align-items:flex-start;justify-content:space-between;gap:8px;width:100%')}>
                    <span className="msym" aria-hidden="true" style={s("font-family:'Material Symbols Outlined';font-variation-settings:'wght' 200;font-size:40px;line-height:1;color:rgb(204,21,23);width:40px;height:40px;overflow:hidden")}>
                      {SERVICE_ICON[sv.slug] || 'build'}
                    </span>
                    {sv.badge && <span style={s('padding:5px 10px;border-radius:999px;background:rgb(204,21,23);font-family:K2D,Jost,sans-serif;font-size:13px;line-height:1')}>{sv.badge}</span>}
                  </div>
                  <span style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:24px;line-height:1.05")}>{sv.title}</span>
                  <span style={s('font-family:K2D,Jost,sans-serif;font-weight:300;font-size:15px;color:rgb(184,184,184);line-height:1.3')}>{sv.short_description}</span>
                  <div style={s('display:flex;flex-direction:column;gap:6px;flex:1')}>
                    {sv.items.slice(0, 4).map((it) => (
                      <span key={it} style={s('display:flex;gap:8px;font-family:K2D,Jost,sans-serif;font-weight:300;font-size:15px;line-height:1.3')}>
                        <span style={s('color:rgb(204,21,23)')}>—</span>
                        {it}
                      </span>
                    ))}
                  </div>
                  <span style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:17px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.12);width:100%")}>Оставить заявку →</span>
                </button>
              ) : (
                <div key={i} style={s('flex:none;width:clamp(270px,21vw,300px);height:340px;border-radius:23px;background:rgb(30,30,30);animation:gspulse 1.2s ease-in-out infinite')} />
              ),
            )}
          </div>
          {!m && (
            <button onClick={() => scrollRib(1)} aria-label="Вперёд" className="hv-bd-accent" style={s('width:52px;height:52px;flex:none;border-radius:50%;border:1px solid rgba(255,255,255,0.3);background:transparent;color:#fff;font-size:22px;cursor:pointer')}>
              →
            </button>
          )}
        </div>
      </section>

      <section id="form" data-screen-label="Форма заявки" style={s('padding:clamp(48px,7vw,126px) clamp(12px,7.8vw,118px) clamp(48px,6vw,96px);display:flex;justify-content:center')}>
        <div style={s('width:100%;max-width:1203px')}>
          <RequestForm mode="main" onSubmitted={setConfirm} />
        </div>
      </section>

      <section id="zone" data-screen-label="Зона выезда" style={s('padding:clamp(40px,6vw,96px) clamp(16px,7.8vw,112px);display:flex;flex-direction:column;gap:28px')}>
        <div style={s('display:flex;flex-direction:column;gap:12px')}>
          <h2 style={s(H2)}>Зона выезда</h2>
          <span style={s('font-size:17px;color:rgb(184,184,184);max-width:620px')}>Отметьте, где стоит машина, — сразу скажем, как быстро приедем.</span>
        </div>
        <MapZone mode="section" onPick={(p) => openForm({ type: 'visit', point: p })} />
      </section>

      <section id="prices" data-screen-label="Калькулятор" style={s('padding:clamp(40px,6vw,96px) clamp(16px,7.8vw,112px);display:flex;flex-direction:column;gap:28px')}>
        <h2 style={s(H2)}>Калькулятор стоимости</h2>
        <Calculator />
      </section>

      {stats.length > 0 && (
        <section data-screen-label="Цифры" style={s('padding:clamp(40px,6vw,96px) clamp(16px,7.8vw,112px)')}>
          <div style={s('display:grid;grid-template-columns:repeat(auto-fit,minmax(min(200px,44%),1fr));gap:32px 24px')}>
            {stats.map((x) => (
              <div key={x.l} style={s('display:flex;flex-direction:column;gap:10px;padding-top:16px;border-top:1px solid rgb(204,21,23)')}>
                <span style={s('font-family:K2D,Jost,sans-serif;font-weight:100;font-size:clamp(44px,4.4vw,64px);line-height:1')}>{x.n}</span>
                <span style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:18px;line-height:1.2;color:rgb(184,184,184)")}>{x.l}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section data-screen-label="Преимущества">
        <div style={s('height:clamp(240px,47vw,680px);background:url(/assets/hero-2.webp) center 30% / cover no-repeat;filter:grayscale(1)')} />
        <h2 style={s("margin:0;padding:24px 16px clamp(32px,4vw,64px);text-align:center;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:clamp(44px,6.67vw,96px);line-height:1;color:rgb(204,21,23)")}>Наши преимущества</h2>
        <div style={s('display:grid;grid-template-columns:repeat(auto-fit,minmax(min(360px,100%),1fr));gap:40px 24px;padding:0 clamp(16px,2vw,24px) clamp(48px,6vw,96px)')}>
          {advantages.map((a) => (
            <div key={a.t} style={s('display:flex;gap:16px;align-items:center')}>
              <div aria-hidden="true" style={s('width:clamp(110px,13vw,190px);aspect-ratio:1;flex:none;display:flex;align-items:center;justify-content:center;font-family:K2D,Jost,sans-serif;font-weight:100;font-size:clamp(88px,10vw,150px);line-height:1;color:rgb(214,214,214)')}>
                {a.n}
              </div>
              <div style={s('display:flex;flex-direction:column;gap:6px')}>
                <span style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:600;font-size:clamp(18px,1.6vw,22px);line-height:1.05")}>{a.t}</span>
                <span style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:clamp(17px,1.6vw,22px);line-height:1.1;color:rgb(214,214,214)")}>{a.d}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section data-screen-label="Мы ремонтируем" style={s('padding:clamp(32px,4vw,56px) 0;border-top:1px solid rgba(255,255,255,0.08);border-bottom:1px solid rgba(255,255,255,0.08);display:flex;flex-direction:column;gap:20px;overflow:hidden')}>
        <h2 style={s("margin:0;padding:0 clamp(16px,7.8vw,112px);font-family:'Josefin Sans',Jost,sans-serif;font-weight:600;font-size:16px;letter-spacing:0.08em;color:rgb(184,184,184)")}>МЫ РЕМОНТИРУЕМ</h2>
        <div className="marquee" aria-label={brandsLine.join(', ')} style={s('display:flex;width:max-content;animation:gsmarquee 45s linear infinite')}>
          {[...brandsLine, ...brandsLine].map((t, i) => (
            <span key={i} aria-hidden="true" style={s("display:inline-flex;align-items:center;gap:40px;padding-right:40px;font-family:'Josefin Sans',Jost,sans-serif;font-weight:200;font-size:clamp(30px,3.4vw,48px);color:#fff;white-space:nowrap")}>
              {t}
              <span style={s('width:8px;height:8px;border-radius:50%;background:rgb(204,21,23)')} />
            </span>
          ))}
        </div>
      </section>

      <Reviews />

      <section id="corp" data-screen-label="Корпоративным клиентам" style={s('padding:clamp(40px,6vw,96px) clamp(16px,7.8vw,112px);display:flex;flex-wrap:wrap;gap:32px;align-items:flex-start')}>
        <div style={s('flex:1 1 340px;min-width:0;display:flex;flex-direction:column;gap:20px')}>
          <h2 style={s(H2)}>Корпоративным клиентам</h2>
          <span style={s('font-size:18px;line-height:1.45;color:rgb(214,214,214);max-width:520px')}>Обслуживаем автопарки и логистические компании по договору. Один контакт на весь парк, документы — без задержек.</span>
          <div style={s('display:flex;flex-direction:column;gap:12px')}>
            {CORP_POINTS.map((p) => (
              <span key={p} style={s("display:flex;gap:12px;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:21px;line-height:1.2")}>
                <span style={s('color:rgb(204,21,23)')}>—</span>
                {p}
              </span>
            ))}
          </div>
        </div>
        <div style={s('flex:1 1 520px;min-width:0')}>
          <RequestForm mode="corp" onSubmitted={setConfirm} />
        </div>
      </section>

      <section id="contacts" data-screen-label="Контакты" style={s('padding:clamp(40px,6vw,96px) clamp(16px,7.8vw,112px);display:flex;flex-direction:column;gap:28px')}>
        <h2 style={s(H2)}>Контакты</h2>
        <div style={s('display:flex;flex-wrap:wrap;gap:24px')}>
          <div style={s('flex:1 1 560px;min-width:0;aspect-ratio:16/9;position:relative;overflow:hidden;border-radius:23px;min-height:260px')}>
            <DgisMap center={center} radiusKm={data?.dispatch_zone.radius_km || 15} zoom={settings?.address.map_zoom || 15} showZone={false} stoLabel="ГрузСпецСервис · СТО" style={s('position:absolute;inset:0')} />
            <a href={twoGisFirm} target="_blank" rel="noopener" style={s('position:absolute;right:14px;top:14px;z-index:3;height:40px;padding:0 14px;border-radius:13px;background:rgb(42,42,42);display:flex;align-items:center;font-size:14px;box-shadow:0 6px 16px rgba(0,0,0,0.4)')}>
              Открыть в 2ГИС ↗
            </a>
          </div>
          <div style={s('flex:1 1 320px;min-width:0;display:flex;flex-direction:column;gap:18px;font-size:17px')}>
            <div style={s('display:flex;flex-direction:column;gap:4px')}>
              <span style={s('font-size:13px;color:rgb(150,150,150)')}>Адрес</span>
              <span>{c.address}</span>
            </div>
            <div style={s('display:flex;flex-direction:column;gap:4px')}>
              <span style={s('font-size:13px;color:rgb(150,150,150)')}>Телефон</span>
              <a href={c.phoneHref} style={s('font-size:26px;font-weight:300')}>
                {c.phoneDisplay}
              </a>
            </div>
            {c.email && (
              <div style={s('display:flex;flex-direction:column;gap:4px')}>
                <span style={s('font-size:13px;color:rgb(150,150,150)')}>E-mail</span>
                <a href={`mailto:${c.email}`}>{c.email}</a>
              </div>
            )}
            <div style={s('display:flex;flex-direction:column;gap:4px')}>
              <span style={s('font-size:13px;color:rgb(150,150,150)')}>Режим работы</span>
              <span style={s('display:flex;align-items:center;gap:8px')}>
                <span style={s('width:8px;height:8px;border-radius:50%;background:oklch(0.72 0.17 150);flex:none')} />
                {c.hours}
              </span>
            </div>
            <div style={s('display:flex;flex-wrap:wrap;gap:10px')}>
              {c.tgUrl && (
                <a href={c.tgUrl} target="_blank" rel="noopener" style={s('flex:1 1 120px;height:48px;border-radius:13px;background:rgb(42,42,42);display:flex;align-items:center;justify-content:center')}>
                  Telegram
                </a>
              )}
              {c.maxUrl && (
                <a href={c.maxUrl} target="_blank" rel="noopener" style={s('flex:1 1 120px;height:48px;border-radius:13px;background:rgb(42,42,42);display:flex;align-items:center;justify-content:center')}>
                  Max
                </a>
              )}
            </div>
            {c.botUrl && (
              <a href={c.botUrl} target="_blank" rel="noopener" className="hv-accent" style={s("height:52px;border-radius:13px;background:rgb(204,21,23);display:flex;align-items:center;justify-content:center;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:20px;color:#fff")}>
                Написать в Telegram-бот
              </a>
            )}
          </div>
        </div>
      </section>

      {confirm && <ConfirmModal data={confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

/**
 * Horizontal review track for a mouse: the scrollbar is hidden and a wheel scrolls the page, so on a desktop
 * without a touchpad the reviews could not be scrolled at all. Adds ‹ › paging and drag-to-scroll (mouse only;
 * touch keeps the native swipe).
 */
function useReviewTrack(count: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ canPrev: false, canNext: false });
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ x: number; left: number; moved: boolean } | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () =>
      setEdges({ canPrev: el.scrollLeft > 4, canNext: el.scrollLeft + el.clientWidth < el.scrollWidth - 4 });
    update();
    el.addEventListener('scroll', update, { passive: true });
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => {
      el.removeEventListener('scroll', update);
      ro.disconnect();
    };
  }, [count]);

  const page = (dir: -1 | 1) => {
    const el = ref.current;
    if (!el) return;
    const card = el.firstElementChild as HTMLElement | null;
    const step = card ? card.offsetWidth + 16 : el.clientWidth * 0.8;
    // Whole cards that fit on screen, at least one.
    const n = Math.max(1, Math.floor((el.clientWidth - 2 * parseFloat(getComputedStyle(el).paddingLeft)) / step));
    el.scrollBy({ left: dir * n * step, behavior: 'smooth' });
  };

  const justDragged = useRef(false);
  const end = () => {
    if (drag.current?.moved) {
      justDragged.current = true; // the click event fires right after pointerup
      setTimeout(() => (justDragged.current = false), 0);
    }
    drag.current = null;
    setDragging(false);
  };

  const handlers = {
    onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => {
      if (e.pointerType !== 'mouse' || e.button !== 0 || !ref.current) return;
      drag.current = { x: e.clientX, left: ref.current.scrollLeft, moved: false };
    },
    onPointerMove: (e: React.PointerEvent<HTMLDivElement>) => {
      const d = drag.current;
      const el = ref.current;
      if (!d || !el) return;
      const dx = e.clientX - d.x;
      if (!d.moved && Math.abs(dx) < 5) return; // a plain click on «Подробнее о ремонте» stays a click
      if (!d.moved) {
        d.moved = true;
        setDragging(true);
        el.setPointerCapture(e.pointerId);
      }
      el.scrollLeft = d.left - dx;
    },
    onPointerUp: () => end(),
    onPointerCancel: () => end(),
    // Swallow the click that ends a drag, so it does not toggle a case under the cursor.
    onClickCapture: (e: React.MouseEvent) => {
      if (justDragged.current) e.stopPropagation();
    },
  };

  return { ref, page, handlers, dragging, ...edges };
}

function Reviews() {
  const { data } = useSite();
  const settings = data?.settings;
  const [items, setItems] = useState<Review[]>(data?.reviews.top || []);
  const [caseId, setCaseId] = useState<number | null>(null);
  const [cs, setCs] = useState<CaseOut | null>(null);
  const [caseErr, setCaseErr] = useState(false);
  const [cmp, setCmp] = useState(50);
  const track = useReviewTrack(items.length);
  const summary = data?.reviews.summary;
  const links = summary?.review_links || settings?.review_links || {};
  const placeholders = links.placeholders || [];

  useEffect(() => {
    api<{ items: Review[] }>('/reviews?limit=20')
      .then((r) => setItems(r.items))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (caseId == null) return;
    setCs(null);
    setCaseErr(false);
    api<CaseOut>(`/cases/${caseId}`)
      .then(setCs)
      .catch(() => setCaseErr(true));
  }, [caseId]);

  const sources = Object.entries(summary?.by_source || {}).filter(([k]) => k !== 'own');
  const before = cs?.photos.before[0];
  const after = cs?.photos.after[0];
  const car = cs ? [cs.vehicle.brand, cs.vehicle.model, cs.vehicle.year].filter(Boolean).join(' ') : '';

  return (
    <section id="reviews" data-screen-label="Отзывы" style={s('padding:clamp(40px,6vw,96px) 0;display:flex;flex-direction:column;gap:28px')}>
      <div style={s('padding:0 clamp(16px,7.8vw,112px);display:flex;flex-wrap:wrap;gap:24px;align-items:flex-end;justify-content:space-between')}>
        <div style={s('display:flex;flex-direction:column;gap:16px')}>
          <h2 style={s(H2)}>Отзывы</h2>
          {summary && (
            <div style={s('display:flex;flex-wrap:wrap;align-items:center;gap:20px')}>
              <div style={s('display:flex;align-items:baseline;gap:10px')}>
                <span style={s('font-weight:100;font-size:64px;line-height:1')}>{avg(summary.average_rating)}</span>
                <span style={s('color:rgb(255,136,0);font-size:22px;letter-spacing:2px')} aria-label={`Рейтинг ${avg(summary.average_rating)} из 5`}>
                  {stars(summary.average_rating)}
                </span>
              </div>
              <div style={s('display:flex;flex-direction:column;gap:4px;font-size:15px;color:rgb(184,184,184)')}>
                {sources.map(([k, v]) => (
                  <span key={k}>
                    {v.label} · {avg(v.average)} · {v.count} {plural(v.count, 'отзыв', 'отзыва', 'отзывов')}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
        <div style={s('display:flex;flex-wrap:wrap;gap:10px')}>
          {(track.canPrev || track.canNext) && (
            <div style={s('display:flex;gap:10px')}>
              {(['prev', 'next'] as const).map((dir) => {
                const enabled = dir === 'prev' ? track.canPrev : track.canNext;
                return (
                  <button
                    key={dir}
                    onClick={() => track.page(dir === 'prev' ? -1 : 1)}
                    disabled={!enabled}
                    aria-label={dir === 'prev' ? 'Предыдущие отзывы' : 'Следующие отзывы'}
                    className={enabled ? 'hv-bd-accent' : undefined}
                    style={sx('width:48px;height:48px;border-radius:13px;border:1px solid rgba(255,255,255,0.3);background:transparent;color:#fff;font-size:22px;line-height:1;cursor:pointer', { opacity: enabled ? 1 : 0.35, cursor: enabled ? 'pointer' : 'default' })}
                  >
                    {dir === 'prev' ? '‹' : '›'}
                  </button>
                );
              })}
            </div>
          )}
          {links.yandex && !placeholders.includes('yandex') && (
            <a href={links.yandex} target="_blank" rel="noopener" className="hv-bd-accent" style={s('height:48px;padding:0 18px;border-radius:13px;border:1px solid rgba(255,255,255,0.3);display:flex;align-items:center;gap:8px;font-size:16px')}>
              Отзывы на Яндексе ↗
            </a>
          )}
          {links['2gis'] && !placeholders.includes('2gis') && (
            <a href={links['2gis']} target="_blank" rel="noopener" className="hv-bd-accent" style={s('height:48px;padding:0 18px;border-radius:13px;border:1px solid rgba(255,255,255,0.3);display:flex;align-items:center;gap:8px;font-size:16px')}>
              Отзывы на 2ГИС ↗
            </a>
          )}
        </div>
      </div>
      <div
        ref={track.ref}
        {...track.handlers}
        style={sx('display:flex;gap:16px;overflow-x:auto;scrollbar-width:none;padding:4px clamp(16px,7.8vw,112px) 8px;scroll-padding:0 clamp(16px,7.8vw,112px)', {
          // Snapping fights a mouse drag: switch it off while dragging, it re-snaps on release.
          scrollSnapType: track.dragging ? 'none' : 'x mandatory',
          cursor: track.canPrev || track.canNext ? (track.dragging ? 'grabbing' : 'grab') : undefined,
          userSelect: track.dragging ? 'none' : undefined,
        })}
      >
        {items.map((r) => (
          <div key={r.id} style={sx('flex:none;width:clamp(290px,26vw,380px);scroll-snap-align:start;display:flex;flex-direction:column;gap:12px;padding:22px;border-radius:23px;background:rgb(30,30,30)', { boxShadow: `inset 0 0 0 1px ${caseId === r.id ? 'rgb(204,21,23)' : 'rgba(255,255,255,0.04)'}` })}>
            <div style={s('display:flex;justify-content:space-between;gap:12px;align-items:flex-start')}>
              <div style={s('display:flex;flex-direction:column;gap:4px')}>
                <span style={s('font-size:17px;font-weight:400')}>{r.author}</span>
                <span style={s('font-size:13px;color:rgb(150,150,150)')}>
                  {fmtDate(r.date)} · {SOURCE_SHORT[r.source] || r.source_label}
                </span>
              </div>
              <span style={s('color:rgb(255,136,0);font-size:15px;letter-spacing:1px;white-space:nowrap')} aria-label={`${r.rating} из 5`}>
                {stars(r.rating)}
              </span>
            </div>
            <span style={s('font-size:16px;line-height:1.45;font-weight:300;flex:1')}>{r.text}</span>
            <div style={s('display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px')}>
              {r.vehicle_brand ? <span style={s('padding:5px 10px;border-radius:999px;background:rgb(42,42,42);font-size:13px')}>{r.vehicle_brand}</span> : <span />}
              {r.has_case && r.case_id && (
                <button
                  onClick={() => {
                    setCaseId(caseId === r.case_id ? null : r.case_id);
                    setCmp(50);
                  }}
                  aria-expanded={caseId === r.case_id}
                  style={s('padding:0 0 3px;border:0;border-bottom:1px solid rgb(204,21,23);background:transparent;color:#fff;font-family:K2D,Jost,sans-serif;font-size:15px;cursor:pointer')}
                >
                  {caseId === r.case_id ? 'Скрыть ремонт' : 'Подробнее о ремонте'}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      {caseId != null && (
        <div style={s('margin:0 clamp(16px,7.8vw,112px);display:flex;flex-wrap:wrap;gap:24px;padding:clamp(18px,2.4vw,32px);border-radius:23px;background:rgb(30,30,30);border:1px solid rgba(204,21,23,0.5)')}>
          <div style={s('flex:1 1 340px;min-width:0;display:flex;flex-direction:column;gap:16px')}>
            <div style={s('display:flex;justify-content:space-between;gap:12px;align-items:flex-start')}>
              <span style={s("font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:28px;line-height:1.05")}>{cs ? car || cs.title : caseErr ? 'Не удалось загрузить' : 'Загружаем…'}</span>
              <button onClick={() => setCaseId(null)} aria-label="Свернуть" style={s('width:40px;height:40px;flex:none;border-radius:50%;border:0;background:rgb(42,42,42);color:#fff;font-size:18px;cursor:pointer')}>
                ×
              </button>
            </div>
            {cs && (
              <>
                <div style={s('display:flex;flex-direction:column;gap:4px')}>
                  <span style={s('font-size:13px;color:rgb(150,150,150)')}>Проблема</span>
                  <span style={s('font-size:17px')}>{cs.problem}</span>
                </div>
                <div style={s('display:flex;flex-direction:column;gap:6px')}>
                  <span style={s('font-size:13px;color:rgb(150,150,150)')}>Что сделали</span>
                  {cs.work_done.map((d) => (
                    <span key={d} style={s('display:flex;gap:8px;font-size:16px')}>
                      <span style={s('color:rgb(204,21,23)')}>—</span>
                      {d}
                    </span>
                  ))}
                </div>
                <div style={s('display:flex;gap:32px;flex-wrap:wrap')}>
                  <div style={s('display:flex;flex-direction:column;gap:4px')}>
                    <span style={s('font-size:13px;color:rgb(150,150,150)')}>Срок</span>
                    <span style={s('font-size:20px')}>{hours(cs.duration_hours)}</span>
                  </div>
                  {cs.price_from != null && (
                    <div style={s('display:flex;flex-direction:column;gap:4px')}>
                      <span style={s('font-size:13px;color:rgb(150,150,150)')}>Стоимость</span>
                      <span style={s('font-size:20px')}>от {rub(cs.price_from)}</span>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
          <div style={s('flex:1 1 420px;min-width:0;display:flex;flex-direction:column;gap:8px')}>
            <div style={s('position:relative;aspect-ratio:4/3;border-radius:16px;overflow:hidden;background:repeating-linear-gradient(135deg, rgb(40,44,40) 0 12px, rgb(32,36,32) 12px 24px)')}>
              {after ? (
                <img src={after.url} alt={after.caption || 'После ремонта'} style={s('position:absolute;inset:0;width:100%;height:100%;object-fit:cover')} />
              ) : (
                <span style={s('position:absolute;right:16px;bottom:14px;font-family:ui-monospace,Menlo,monospace;font-size:12px;color:rgb(184,184,184)')}>фото после ремонта</span>
              )}
              <div style={sx('position:absolute;inset:0;overflow:hidden;background:repeating-linear-gradient(135deg, rgb(48,36,36) 0 12px, rgb(38,30,30) 12px 24px)', { clipPath: `inset(0 ${100 - cmp}% 0 0)` })}>
                {before ? (
                  <img src={before.url} alt={before.caption || 'До ремонта'} style={s('position:absolute;inset:0;width:100%;height:100%;object-fit:cover')} />
                ) : (
                  <span style={s('position:absolute;left:16px;bottom:14px;font-family:ui-monospace,Menlo,monospace;font-size:12px;color:rgb(184,184,184);white-space:nowrap')}>фото до ремонта</span>
                )}
              </div>
              <div style={sx('position:absolute;top:0;bottom:0;width:2px;margin-left:-1px;background:#fff;pointer-events:none', { left: `${cmp}%` })}>
                <span style={s('position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:40px;height:40px;border-radius:50%;background:rgb(204,21,23);border:2px solid #fff;display:flex;align-items:center;justify-content:center;font-size:14px')}>⇆</span>
              </div>
              <input type="range" min={0} max={100} value={cmp} onChange={(e) => setCmp(+e.target.value)} aria-label="Сравнить до и после" style={s('position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:ew-resize;margin:0')} />
              <span style={s('position:absolute;left:12px;top:12px;padding:4px 10px;border-radius:999px;background:rgba(0,0,0,0.6);font-size:13px;pointer-events:none')}>До</span>
              <span style={s('position:absolute;right:12px;top:12px;padding:4px 10px;border-radius:999px;background:rgba(0,0,0,0.6);font-size:13px;pointer-events:none')}>После</span>
            </div>
            <span style={s('font-size:13px;color:rgb(150,150,150)')}>{before?.caption && after?.caption ? `${before.caption} → ${after.caption}` : 'Потяните, чтобы сравнить'}</span>
          </div>
        </div>
      )}
    </section>
  );
}
