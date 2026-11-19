import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { s } from '../lib/css';
import { useSite } from '../site';

/**
 * 2GIS MapGL map with the dispatch zone, the service station marker and a picked point.
 *
 * The browser key comes from the backend (`/settings/public → maps.mapgl_key`). Without a key, or when
 * WebGL is unavailable, it falls back to the schematic map from the design: still clickable — clicks are
 * converted to coordinates around the station, so the dispatch-zone check keeps working.
 */

type MapglModule = typeof import('@2gis/mapgl/types');
type MapInstance = InstanceType<MapglModule['Map']>;
type HtmlMarkerInstance = InstanceType<MapglModule['HtmlMarker']>;

let mapglPromise: Promise<MapglModule> | null = null;
function loadMapgl(): Promise<MapglModule> {
  if (!mapglPromise) {
    mapglPromise = import('@2gis/mapgl').then((m) => m.load()).catch((e) => {
      mapglPromise = null;
      throw e;
    });
  }
  return mapglPromise;
}

export interface LatLon {
  lat: number;
  lon: number;
}

interface Props {
  center: LatLon; // service station
  radiusKm: number;
  zoom: number;
  point?: LatLon | null;
  /** Increment to pan the map to `point` (after search / geolocation). */
  focusKey?: number;
  onPick?: (p: LatLon) => void;
  showZone?: boolean;
  zoneLabel?: string;
  stoLabel?: string;
  style?: CSSProperties;
  /** Ratio of the zone diameter to the fallback map size (matches the design's schematic). */
  fallbackZoneRatio?: number;
}

const KM_PER_DEG_LAT = 111.32;

function stoHtml(label: string): string {
  return `<div style="width:160px;display:flex;flex-direction:column;align-items:center;gap:4px;pointer-events:none">
    <div style="width:40px;height:40px;border-radius:50%;background:rgb(204,21,23) url(/assets/logo.webp) center 30% / 70% no-repeat;border:2px solid #fff;box-shadow:0 4px 12px rgba(0,0,0,.5)"></div>
    <span style="font:12px K2D,Jost,sans-serif;color:#fff;background:rgb(18,18,18);padding:2px 8px;border-radius:999px;white-space:nowrap">${label}</span>
  </div>`;
}

const PIN_HTML =
  '<div style="width:34px;height:42px;background:url(/assets/icon-b.webp) center / contain no-repeat;filter:invert(1) drop-shadow(0 2px 4px rgba(0,0,0,0.6));pointer-events:none"></div>';

export function DgisMap(props: Props) {
  const { center, radiusKm, zoom, point, focusKey, onPick, showZone = true, zoneLabel, stoLabel = 'СТО' } = props;
  const maps = useSite().data?.settings.maps;
  const key = maps?.mapgl_key || null;
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapInstance | null>(null);
  const libRef = useRef<MapglModule | null>(null);
  const pinRef = useRef<HtmlMarkerInstance | null>(null);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);

  // Create the map once per key.
  useEffect(() => {
    if (!key || !ref.current) return;
    let destroyed = false;
    let map: MapInstance | null = null;
    loadMapgl()
      .then((mapgl) => {
        if (destroyed || !ref.current) return;
        if (!mapgl.isSupported()) {
          setFailed(true);
          return;
        }
        libRef.current = mapgl;
        map = new mapgl.Map(ref.current, {
          key,
          center: [center.lon, center.lat],
          zoom,
          style: maps?.style || undefined,
          zoomControl: 'bottomRight',
          lang: 'ru',
        });
        mapRef.current = map;
        if (showZone) {
          new mapgl.Circle(map, {
            coordinates: [center.lon, center.lat],
            radius: radiusKm * 1000,
            color: '#cc151724',
            strokeColor: '#cc1517b3',
            strokeWidth: 2,
          });
        }
        new mapgl.HtmlMarker(map, { coordinates: [center.lon, center.lat], html: stoHtml(stoLabel), anchor: [80, 20], zIndex: 1 });
        map.on('click', (e) => {
          const [lon, lat] = e.lngLat;
          pickRef.current?.({ lat, lon });
        });
        setReady(true);
      })
      .catch(() => !destroyed && setFailed(true));
    return () => {
      destroyed = true;
      pinRef.current = null;
      mapRef.current = null;
      setReady(false);
      map?.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // Keep the picked-point marker in sync.
  useEffect(() => {
    const map = mapRef.current;
    const mapgl = libRef.current;
    if (!ready || !map || !mapgl) return;
    if (!point) {
      pinRef.current?.destroy();
      pinRef.current = null;
      return;
    }
    if (pinRef.current) pinRef.current.setCoordinates([point.lon, point.lat]);
    else pinRef.current = new mapgl.HtmlMarker(map, { coordinates: [point.lon, point.lat], html: PIN_HTML, anchor: [17, 42], zIndex: 2 });
  }, [ready, point?.lat, point?.lon]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const map = mapRef.current;
    if (ready && map && point && focusKey) map.setCenter([point.lon, point.lat], { duration: 600 });
  }, [focusKey, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  const label = zoneLabel ? (
    <span style={s('position:absolute;left:50%;top:12px;transform:translateX(-50%);font-size:13px;color:rgb(255,180,180);background:rgba(18,18,18,0.85);padding:4px 10px;border-radius:999px;pointer-events:none;white-space:nowrap;z-index:2;font-family:K2D,Jost,sans-serif')}>
      {zoneLabel}
    </span>
  ) : null;

  if (key && !failed) {
    return (
      <div className={maps?.style ? undefined : 'map-dim'} style={{ ...s('position:relative;overflow:hidden;background:rgb(26,28,30)'), ...props.style }}>
        <div ref={ref} style={s('position:absolute;inset:0')} />
        {label}
      </div>
    );
  }
  return <FallbackMap {...props} label={label} />;
}

/** The design's schematic map, made functional (click → coordinates around the station). */
function FallbackMap(props: Props & { label: React.ReactNode }) {
  const { center, radiusKm, point, onPick, showZone = true, fallbackZoneRatio = 0.32, label } = props;
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 500 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect();
      setSize({ w: r.width, h: r.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const diameterPx = Math.min(size.w, size.h * 1.6) * fallbackZoneRatio;
  const pxPerKm = diameterPx / (radiusKm * 2);
  const kmPerDegLon = KM_PER_DEG_LAT * Math.cos((center.lat * Math.PI) / 180);
  const toPx = (p: LatLon) => ({
    x: size.w / 2 + (p.lon - center.lon) * kmPerDegLon * pxPerKm,
    y: size.h / 2 - (p.lat - center.lat) * KM_PER_DEG_LAT * pxPerKm,
  });
  const pin = point ? toPx(point) : null;
  const click = (e: React.MouseEvent) => {
    if (!onPick || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const dxKm = (e.clientX - r.left - r.width / 2) / pxPerKm;
    const dyKm = (e.clientY - r.top - r.height / 2) / pxPerKm;
    onPick({ lat: center.lat - dyKm / KM_PER_DEG_LAT, lon: center.lon + dxKm / kmPerDegLon });
  };
  return (
    <div
      ref={ref}
      onClick={click}
      style={{
        ...s('position:relative;overflow:hidden;background-color:rgb(26,28,30);background-image:linear-gradient(rgba(255,255,255,0.045) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,0.045) 1px,transparent 1px);background-size:48px 48px'),
        cursor: onPick ? 'crosshair' : 'default',
        ...props.style,
      }}
    >
      <div style={s('position:absolute;left:58%;top:-10%;width:7%;height:120%;background:rgba(80,110,140,0.22);transform:rotate(14deg)')} />
      {showZone && (
        <div style={{ ...s('position:absolute;left:50%;top:50%;aspect-ratio:1;transform:translate(-50%,-50%);border-radius:50%;background:rgba(204,21,23,0.14);border:1.5px dashed rgba(204,21,23,0.7);pointer-events:none'), width: diameterPx }} />
      )}
      <div style={s('position:absolute;left:50%;top:50%;transform:translate(-50%,-20px);display:flex;flex-direction:column;align-items:center;gap:4px;pointer-events:none')}>
        <div style={s('width:40px;height:40px;border-radius:50%;background:rgb(204,21,23) url(/assets/logo.webp) center 30% / 70% no-repeat;border:2px solid #fff')} />
        <span style={s('font-size:12px;background:rgb(18,18,18);padding:2px 8px;border-radius:999px')}>{props.stoLabel || 'СТО'}</span>
      </div>
      {pin && (
        <div style={{ ...s('position:absolute;transform:translate(-50%,-100%);width:34px;height:42px;background:url(/assets/icon-b.webp) center / contain no-repeat;filter:invert(1) drop-shadow(0 2px 4px rgba(0,0,0,0.6));pointer-events:none'), left: pin.x, top: pin.y }} />
      )}
      {label}
      <span style={s('position:absolute;left:14px;bottom:12px;font-family:ui-monospace,Menlo,monospace;font-size:11px;color:rgb(128,128,128);pointer-events:none')}>
        схема · карта 2ГИС появится после настройки ключа
      </span>
    </div>
  );
}
