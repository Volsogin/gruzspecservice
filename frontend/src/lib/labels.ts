/** Short UI labels for backend slugs (the design uses compact chips). Unknown slugs fall back to API titles. */

export const VEHICLE_SHORT: Record<string, string> = {
  tractor: 'Тягач',
  dump: 'Самосвал',
  semitrailer: 'Полуприцеп',
  truck: 'Бортовой / фургон',
  special: 'Спецтехника',
};

export const VEHICLE_ORDER = ['tractor', 'dump', 'semitrailer', 'truck', 'special'];

export const WORK_SHORT: Record<string, string> = {
  diagnostics: 'Диагностика',
  maintenance: 'ТО',
  chassis: 'Ходовая',
  brakes: 'Тормоза',
  engine: 'Двигатель',
  transmission: 'КПП и сцепление',
  pneumatics: 'Пневмосистема',
  fuel: 'Топливная',
  electrics: 'Автоэлектрика',
  towing: 'Эвакуация',
};

/** Material Symbols for service cards, by service slug (the API's own icon names are for other sets). */
export const SERVICE_ICON: Record<string, string> = {
  'sto-repair': 'garage',
  'onsite-repair': 'local_shipping',
  'onsite-diagnostics': 'troubleshoot',
  'auto-electrician': 'electric_bolt',
  'tow-truck': 'car_crash',
  parts: 'settings',
  'engine-heating': 'local_fire_department',
  batteries: 'battery_charging_full',
  'fleet-service': 'apartment',
};

/** Default problem text when a card opens the generic «Выезд мастера» form. */
export const SERVICE_PROBLEM: Record<string, string> = {
  'onsite-diagnostics': 'Нужна выездная диагностика',
  'auto-electrician': 'Проблема с электрикой',
  'engine-heating': 'Нужен отогрев двигателя',
  batteries: 'Сел аккумулятор, нужен запуск',
};

export const STATUS_COLOR: Record<string, string> = {
  new: 'oklch(0.72 0.12 240)',
  accepted: 'oklch(0.72 0.12 290)',
  on_the_way: 'oklch(0.75 0.15 55)',
  in_progress: 'oklch(0.82 0.16 85)',
  completed: 'oklch(0.72 0.17 150)',
  cancelled: 'rgb(150,150,150)',
};

export function softColor(c: string, alpha = 0.14): string {
  return c.startsWith('oklch') ? c.replace(')', ` / ${alpha})`) : 'rgba(150,150,150,0.14)';
}

export const SOURCE_SHORT: Record<string, string> = { yandex: 'Яндекс', '2gis': '2ГИС', own: 'Сайт' };
