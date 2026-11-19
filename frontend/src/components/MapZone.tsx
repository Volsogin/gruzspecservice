import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type GeoItem, type ZoneCheck } from '../lib/api';
import type { MapPoint } from '../lib/bus';
import { s, sx } from '../lib/css';
import { useContacts, useSite } from '../site';
import { DgisMap, type LatLon } from './DgisMap';

interface Props {
  mode: 'section' | 'picker';
  initial?: MapPoint | null;
  onPick?: (p: MapPoint) => void;
  onClose?: () => void;
}

const PLATES = {
  inside: ['oklch(0.72 0.17 150 / 0.14)', 'oklch(0.72 0.17 150 / 0.6)', 'oklch(0.85 0.12 150)'],
  region: ['rgb(42,42,42)', 'rgba(255,255,255,0.16)', '#fff'],
  outside: ['oklch(0.82 0.16 85 / 0.14)', 'oklch(0.82 0.16 85 / 0.6)', 'oklch(0.9 0.12 85)'],
} as const;

export function zoneMessage(p: Pick<MapPoint, 'zone' | 'km' | 'mins'>): string {
  if (p.zone === 'inside') return `Вы в зоне быстрого выезда — приедем примерно за ${p.mins ?? 30} минут`;
  if (p.zone === 'region') return `Выезжаем и сюда (${Math.round(p.km)} км). Время и стоимость уточнит диспетчер`;
  return 'Вне зоны обслуживания — позвоните, подскажем';
}

const coordsLabel = (p: LatLon) => `Точка на карте · ${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`;

function withCity(q: string): string {
  return /саратов|энгельс|област|трасс|р-2\d\d|район/i.test(q) ? q : `Саратов, ${q}`;
}

function pickAddress(items: GeoItem[]): string {
  const best = items.find((i) => i.type === 'building' || i.type === 'street') || items[0];
  return best ? best.full_name : '';
}

export function MapZone({ mode, initial, onPick, onClose }: Props) {
  const site = useSite().data;
  const c = useContacts();
  const center = site?.dispatch_zone.center || { lat: 51.607788, lon: 45.923923 };
  const radius = site?.dispatch_zone.radius_km || 15;
  const zoneNote = `В пределах ${Math.round(radius)} км от СТО — около ${site?.dispatch_zone.eta_minutes || 30} минут`;

  const [point, setPoint] = useState<MapPoint | null>(initial || null);
  const [checking, setChecking] = useState(false);
  const [query, setQuery] = useState(initial?.addr || '');
  const [sugs, setSugs] = useState<GeoItem[]>([]);
  const [sugOpen, setSugOpen] = useState(false);
  const [geoOff, setGeoOff] = useState(false);
  const [locating, setLocating] = useState(false);
  const [locErr, setLocErr] = useState('');
  const [focusKey, setFocusKey] = useState(0);
  const seq = useRef(0);

  const choose = async (ll: LatLon, addr?: string, focus = false) => {
    const my = ++seq.current;
    setSugOpen(false);
    setLocErr('');
    setChecking(true);
    // Show the pin immediately; the zone/address arrive a moment later.
    setPoint((p) => ({ lat: ll.lat, lon: ll.lon, addr: addr || '', km: p?.km ?? 0, zone: p?.zone ?? 'region', mins: p?.mins ?? null, message: '' }));
    if (focus) setFocusKey((k) => k + 1);
    const check = api<ZoneCheck>('/dispatch/check', { method: 'POST', json: ll });
    const reverse = addr
      ? Promise.resolve(addr)
      : api<{ items: GeoItem[] }>('/geo/reverse', { method: 'POST', json: ll })
          .then((r) => pickAddress(r.items))
          .catch(() => '');
    try {
      const [z, a] = await Promise.all([check, reverse]);
      if (my !== seq.current) return;
      const p: MapPoint = { lat: ll.lat, lon: ll.lon, addr: a, km: z.distance_km, zone: z.zone, mins: z.eta_minutes, message: z.message };
      setPoint(p);
      if (a && !addr) setQuery(a);
    } catch {
      if (my === seq.current) setLocErr('Не удалось проверить точку — попробуйте ещё раз');
    } finally {
      if (my === seq.current) setChecking(false);
    }
  };

  // Address search (2GIS geocoder via the backend), debounced.
  useEffect(() => {
    const q = query.trim();
    if (!sugOpen || q.length < 3 || geoOff) {
      setSugs([]);
      return;
    }
    const t = setTimeout(() => {
      api<{ items: GeoItem[] }>('/geo/geocode', { method: 'POST', json: { query: withCity(q), limit: 5 } })
        .then((r) => setSugs(r.items.filter((i) => i.type !== 'adm_div' || r.items.length < 3).slice(0, 5)))
        .catch((e) => {
          if (e instanceof ApiError && e.status === 501) setGeoOff(true);
          setSugs([]);
        });
    }, 350);
    return () => clearTimeout(t);
  }, [query, sugOpen, geoOff]);

  const locate = (e?: React.MouseEvent) => {
    e?.stopPropagation();
    if (!window.isSecureContext) {
      // Browsers only allow geolocation over HTTPS (or on localhost).
      setLocErr('Местоположение доступно только по HTTPS — отметьте точку на карте или найдите адрес');
      return;
    }
    if (!navigator.geolocation) {
      setLocErr('Браузер не даёт определить местоположение — отметьте точку на карте');
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        void choose({ lat: pos.coords.latitude, lon: pos.coords.longitude }, undefined, true);
      },
      () => {
        setLocating(false);
        setLocErr('Не получилось определить местоположение. Разрешите доступ к геолокации или отметьте точку на карте');
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 },
    );
  };

  const ready = point && !checking && point.message;
  const pl = PLATES[point?.zone || 'region'];
  const addrLine = point ? `${point.addr || coordsLabel(point)}${ready ? ` · ${String(point.km).replace('.', ',')} км от СТО` : ''}` : '';
  const plateMsg = checking ? 'Проверяем, как быстро приедем…' : point ? zoneMessage(point) : '';
  const confirm = () => point && ready && onPick?.(point);

  const searchBox = (picker: boolean) => (
    <div style={picker ? undefined : s('position:relative')}>
      <input
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setSugOpen(true);
        }}
        onFocus={() => setSugOpen(true)}
        onBlur={() => setTimeout(() => setSugOpen(false), 200)}
        placeholder="Поиск адреса"
        aria-label="Поиск адреса"
        autoComplete="street-address"
        className="fc-accent"
        style={sx('width:100%;box-sizing:border-box;height:52px;padding:0 16px;border-radius:13px;border:1px solid rgba(255,255,255,0.12);background:rgb(42,42,42);color:#fff;font-family:K2D,Jost,sans-serif;font-size:17px;outline:none', picker ? { boxShadow: '0 8px 24px rgba(0,0,0,0.5)' } : {})}
      />
      {sugOpen && (sugs.length > 0 || geoOff) && (
        <div style={picker ? s('margin-top:4px;background:rgb(42,42,42);border-radius:13px;overflow:hidden') : s('position:absolute;left:0;right:0;top:56px;z-index:5;background:rgb(42,42,42);border-radius:13px;overflow:hidden;box-shadow:0 12px 32px rgba(0,0,0,0.5)')}>
          {geoOff ? (
            <span style={s('display:block;padding:12px 16px;color:rgb(184,184,184);font-size:15px')}>Поиск адреса недоступен — отметьте точку на карте</span>
          ) : (
            sugs.map((g, i) => (
              <button
                key={i}
                onMouseDown={(e) => e.preventDefault()}
                onClick={(e) => {
                  e.stopPropagation();
                  setQuery(g.full_name);
                  void choose({ lat: g.lat, lon: g.lon }, g.full_name, true);
                }}
                className="hv-s3"
                style={s(`display:block;width:100%;text-align:left;padding:${picker ? '14px' : '12px'} 16px;border:0;background:transparent;color:#fff;font-family:K2D,Jost,sans-serif;font-size:16px;cursor:pointer`)}
              >
                {g.full_name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );

  const plate = (picker: boolean) =>
    point && (
      <div style={sx(picker ? 'display:flex;flex-direction:column;gap:6px;padding:14px 16px;border-radius:13px' : 'display:flex;flex-direction:column;gap:12px;padding:18px;border-radius:13px', { background: pl[0], border: `1px solid ${pl[1]}` })} aria-live="polite">
        <span style={s('font-size:13px;color:rgb(184,184,184)')}>{addrLine}</span>
        <span style={sx(`font-size:${picker ? 17 : 19}px;font-weight:400;line-height:1.3`, { color: checking ? '#fff' : pl[2] })}>{plateMsg}</span>
      </div>
    );

  if (mode === 'picker') {
    return (
      <div style={s('position:relative;width:100%;height:100%;display:flex;flex-direction:column;background:rgb(18,18,18);font-family:K2D,Jost,sans-serif;color:#fff')}>
        <div style={s('display:flex;align-items:center;gap:12px;padding:12px 12px 12px 20px;border-bottom:1px solid rgba(255,255,255,0.08)')}>
          <span style={s("flex:1;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:22px")}>Где сломались?</span>
          <button onClick={onClose} aria-label="Закрыть" style={s('width:44px;height:44px;border-radius:13px;background:rgb(42,42,42);border:0;color:#fff;font-size:22px;cursor:pointer')}>
            ×
          </button>
        </div>
        <div style={s('flex:1;min-height:0;position:relative')}>
          <DgisMap center={center} radiusKm={radius} zoom={10.4} point={point} focusKey={focusKey} onPick={(ll) => void choose(ll)} style={s('position:absolute;inset:0')} fallbackZoneRatio={0.44} />
          <div style={s('position:absolute;left:12px;right:12px;top:12px;z-index:3')}>{searchBox(true)}</div>
          <button onClick={locate} aria-label="Моё местоположение" style={sx('position:absolute;right:12px;bottom:12px;z-index:3;width:52px;height:52px;border-radius:50%;background:rgb(42,42,42);border:0;display:flex;align-items:center;justify-content:center;box-shadow:0 8px 24px rgba(0,0,0,0.5);cursor:pointer', { opacity: locating ? 0.6 : 1, bottom: 64 })}>
            <span style={s('width:16px;height:16px;border-radius:50%;border:2px solid #fff;box-sizing:border-box;box-shadow:0 0 0 4px rgba(255,255,255,0.15)')} />
          </button>
        </div>
        <div style={s('padding:16px 16px calc(16px + env(safe-area-inset-bottom));display:flex;flex-direction:column;gap:12px;border-top:1px solid rgba(255,255,255,0.08)')}>
          {plate(true)}
          {!point && <span style={s('font-size:15px;color:rgb(184,184,184)')}>{locating ? 'Определяем местоположение…' : 'Нажмите на карту или найдите адрес'}</span>}
          {locErr && <span style={s('font-size:14px;color:rgb(255,107,107)')}>{locErr}</span>}
          <button onClick={confirm} disabled={!ready} style={sx("height:56px;border-radius:13px;border:0;color:#fff;font-family:'Josefin Sans',Jost,sans-serif;font-size:21px;cursor:pointer", { background: ready ? 'rgb(204,21,23)' : 'rgb(58,58,58)', cursor: ready ? 'pointer' : 'default' })}>
            Готово
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={s('display:flex;flex-wrap:wrap;gap:24px;font-family:K2D,Jost,sans-serif;color:#fff')}>
      <DgisMap center={center} radiusKm={radius} zoom={10.4} point={point} focusKey={focusKey} onPick={(ll) => void choose(ll)} zoneLabel={zoneNote} style={s('flex:1 1 560px;min-width:0;aspect-ratio:16/10;border-radius:23px;min-height:300px')} />
      <div style={s('flex:1 1 300px;min-width:0;display:flex;flex-direction:column;gap:16px')}>
        {searchBox(false)}
        <button onClick={locate} className="hv-bd-white" style={s('height:48px;border-radius:13px;border:1px solid rgba(255,255,255,0.2);background:transparent;color:#fff;font-family:K2D,Jost,sans-serif;font-size:16px;display:flex;align-items:center;justify-content:center;gap:10px;cursor:pointer')}>
          <span style={s('width:12px;height:12px;border-radius:50%;border:2px solid #fff;box-sizing:border-box')} />
          {locating ? 'Определяем…' : 'Моё местоположение'}
        </button>
        <span style={s('font-size:15px;color:rgb(184,184,184)')}>Нажмите на карту, найдите адрес или определите местоположение.</span>
        {locErr && <span style={s('font-size:14px;color:rgb(255,107,107)')}>{locErr}</span>}
        {plate(false)}
        {ready && point.zone === 'outside' && (
          <a href={c.phoneHref} style={s("height:52px;border-radius:13px;background:rgb(204,21,23);display:flex;align-items:center;justify-content:center;font-family:'Josefin Sans',Jost,sans-serif;font-size:20px;color:#fff")}>
            Позвонить
          </a>
        )}
        {ready && point.zone !== 'outside' && (
          <button onClick={confirm} className="hv-accent" style={s("height:52px;border-radius:13px;background:rgb(204,21,23);border:0;color:#fff;font-family:'Josefin Sans',Jost,sans-serif;font-size:20px;cursor:pointer")}>
            Вызвать мастера сюда
          </button>
        )}
      </div>
    </div>
  );
}
