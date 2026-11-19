import { useEffect } from 'react';
import { Route, Routes, useLocation } from 'react-router-dom';
import { Chat } from './components/Chat';
import { Footer } from './components/Footer';
import { Header } from './components/Header';
import { s } from './lib/css';
import { Home } from './pages/Home';
import { NotFound } from './pages/NotFound';
import { OrderPage } from './pages/OrderPage';
import { PrivacyPage } from './pages/PrivacyPage';
import { useSite, useWidth } from './site';

const TITLE = 'ГрузСпецСервис — ремонт грузовиков 24/7, Саратов';

function ScrollTop() {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    if (!hash) window.scrollTo(0, 0);
    if (pathname === '/') document.title = TITLE;
  }, [pathname]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

export function App() {
  const { error, data, reload } = useSite();
  const m = useWidth() < 1100;
  return (
    <div style={s('min-height:100vh;display:flex;flex-direction:column;background:rgb(18,18,18);color:#fff;font-family:K2D,Jost,sans-serif;overflow-x:clip')}>
      <ScrollTop />
      <a href="#main" className="skip-link">
        К содержимому
      </a>
      <Header />
      {error && !data && (
        <div role="alert" style={s('margin:16px;padding:14px 18px;border-radius:13px;background:rgba(255,107,107,0.1);border:1px solid rgba(255,107,107,0.5);display:flex;flex-wrap:wrap;gap:12px;align-items:center')}>
          <span style={s('flex:1 1 240px')}>Не удалось загрузить данные сайта. Проверьте интернет — или просто позвоните нам.</span>
          <button onClick={reload} style={s('height:44px;padding:0 18px;border-radius:13px;border:1px solid #fff;background:transparent;color:#fff;font-family:K2D,Jost,sans-serif;font-size:16px;cursor:pointer')}>
            Повторить
          </button>
        </div>
      )}
      <div id="main" style={s('flex:1;display:flex;flex-direction:column')}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/order/:token" element={<OrderPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </div>
      <Footer />
      <Chat />
      {m && <div aria-hidden="true" style={s('height:calc(68px + env(safe-area-inset-bottom))')} />}
    </div>
  );
}
