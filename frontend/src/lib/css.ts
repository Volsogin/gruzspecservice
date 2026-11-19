import type { CSSProperties } from 'react';

/**
 * Turns a CSS declaration string into a React style object.
 *
 * The design prototype is written with inline `style="..."` strings; keeping them verbatim
 * (instead of hand-converting every property to camelCase) keeps the port pixel-faithful and
 * makes it easy to diff against the design. Results are cached per string.
 */
const cache = new Map<string, CSSProperties>();

export function s(css: string): CSSProperties {
  const hit = cache.get(css);
  if (hit) return hit;
  const out: Record<string, string> = {};
  let depth = 0;
  let start = 0;
  const parts: string[] = [];
  for (let i = 0; i < css.length; i++) {
    const c = css[i];
    if (c === '(') depth++;
    else if (c === ')') depth--;
    else if (c === ';' && depth === 0) {
      parts.push(css.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(css.slice(start));
  for (const part of parts) {
    const idx = part.indexOf(':');
    if (idx < 0) continue;
    const prop = part.slice(0, idx).trim();
    const value = part.slice(idx + 1).trim();
    if (!prop) continue;
    const key = prop.startsWith('--') ? prop : prop.replace(/-([a-z])/g, (_, ch: string) => ch.toUpperCase());
    out[key] = value;
  }
  if (cache.size < 2000) cache.set(css, out);
  return out;
}

/** `s()` plus per-render dynamic overrides. */
export function sx(css: string, extra: CSSProperties): CSSProperties {
  return { ...s(css), ...extra };
}

export const C = {
  accent: 'rgb(204,21,23)',
  accentHover: 'rgb(226,38,40)',
  line: 'rgba(255,255,255,0.22)',
  danger: 'rgb(255,107,107)',
  success: 'oklch(0.72 0.17 150)',
  warning: 'oklch(0.82 0.16 85)',
  info: 'oklch(0.72 0.12 240)',
  text2: 'rgb(184,184,184)',
};

export const H2 =
  "margin:0;font-family:'Josefin Sans',Jost,sans-serif;font-weight:300;font-size:clamp(34px,4vw,56px);line-height:1;padding-bottom:14px;border-bottom:1px solid rgb(204,21,23);align-self:flex-start";
