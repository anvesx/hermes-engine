// Small server-rendered SVG charts for the dashboard. No client JS: each column carries an SVG <title>,
// so hovering anywhere in it shows the values, and the weekly table below repeats every number.
import type { ReactNode } from "react";

const WIDE = 640, PAD = { top: 12, right: 8, bottom: 22, left: 44 };

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

/** A bar whose data end (the top) is rounded and whose baseline end is square. */
function bar(x: number, y: number, w: number, h: number, r = 4) {
  if (h <= 0) return "";
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

const weekLabel = (k: string) => `W${k.slice(6)}`;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const dayLabel = (k: string) => `${MONTHS[Number(k.slice(5, 7)) - 1]} ${Number(k.slice(8))}`;

function Frame({ width = WIDE, height, min = 0, max, fmt, labels, label = weekLabel, every = 2, children }:
  { width?: number; height: number; min?: number; max: number; fmt: (n: number) => string; labels: string[];
    label?: (k: string) => string; every?: number; children: ReactNode }) {
  const W = width, ih = height - PAD.top - PAD.bottom, iw = W - PAD.left - PAD.right, step = iw / labels.length;
  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="viz" role="img">
      {[0, 0.5, 1].map((f) => {
        const y = PAD.top + ih * (1 - f);
        return (
          <g key={f}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y} y2={y} className={f === 0 ? "axis" : "grid"} />
            <text x={PAD.left - 6} y={y + 4} textAnchor="end" className="tick">{fmt(min + (max - min) * f)}</text>
          </g>
        );
      })}
      {labels.map((l, i) => (labels.length - 1 - i) % every === 0 && (
        <text key={l} x={PAD.left + step * (i + 0.5)} y={height - 6} textAnchor="middle" className="tick">{label(l)}</text>
      ))}
      {children}
    </svg>
  );
}

/** One measure per week (or day) as bars. The latest one is labelled directly. */
export function WeekBars({ weeks, values, fmt, width = WIDE, height = 150, label, every }:
  { weeks: string[]; values: number[]; fmt: (n: number) => string; width?: number; height?: number;
    label?: (k: string) => string; every?: number }) {
  const W = width, max = niceMax(Math.max(...values)), ih = height - PAD.top - PAD.bottom;
  const step = (W - PAD.left - PAD.right) / weeks.length, bw = Math.min(28, step - 2);
  return (
    <Frame width={W} height={height} max={max} fmt={fmt} labels={weeks} label={label} every={every}>
      {weeks.map((k, i) => {
        const x = PAD.left + step * i + (step - bw) / 2, h = (values[i] / max) * ih, y = PAD.top + ih - h;
        const last = i === weeks.length - 1;
        return (
          <g key={k} className="col">
            <title>{`${label ? label(k) : k}: ${fmt(values[i])}`}</title>
            <rect x={PAD.left + step * i} y={PAD.top} width={step} height={ih} className="hit" />
            <path d={bar(x, y, bw, h)} className={`mark s1${last ? "" : " past"}`} />
            {last && values[i] > 0 && <text x={x + bw / 2} y={y - 4} textAnchor="middle" className="val">{fmt(values[i])}</text>}
          </g>
        );
      })}
    </Frame>
  );
}

/** Points per week, participation stacked under improvement. */
export function PointsBars({ weeks, a, b, height = 170 }: { weeks: string[]; a: number[]; b: number[]; height?: number }) {
  const W = WIDE, max = niceMax(Math.max(...weeks.map((_, i) => a[i] + b[i]))), ih = height - PAD.top - PAD.bottom;
  const step = (W - PAD.left - PAD.right) / weeks.length, bw = Math.min(28, step - 2), px = (n: number) => (n / max) * ih;
  return (
    <Frame height={height} max={max} fmt={(n) => String(Math.round(n))} labels={weeks}>
      {weeks.map((k, i) => {
        const x = PAD.left + step * i + (step - bw) / 2, base = PAD.top + ih;
        const ha = px(a[i]), hb = px(b[i]), gap = ha > 0 && hb > 0 ? 2 : 0;
        return (
          <g key={k} className="col">
            <title>{`${k}: ${a[i] + b[i]} points (participation ${a[i]}, improvement ${b[i]})`}</title>
            <rect x={PAD.left + step * i} y={PAD.top} width={step} height={ih} className="hit" />
            {hb > 0
              ? <rect x={x} y={base - ha} width={bw} height={ha} className="mark s1" />
              : <path d={bar(x, base - ha, bw, ha)} className="mark s1" />}
            <path d={bar(x, base - ha - gap - hb, bw, hb)} className="mark s2" />
          </g>
        );
      })}
    </Frame>
  );
}

/** Waste index per week as a line, against the user's own baseline (dashed). Lower is better. */
export function WasteLine({ weeks, values, baseline, height = 170 }:
  { weeks: string[]; values: (number | null)[]; baseline: number | null; height?: number }) {
  const known = values.filter((v): v is number => v !== null);
  // a line needs no zero baseline: zoom to the data so week-to-week changes are visible
  const hi = Math.max(...known, baseline ?? 0), lo = Math.min(...known, baseline ?? hi);
  const pad = Math.max((hi - lo) * 0.25, hi * 0.05, 0.05);
  const min = Math.max(0, Math.floor((lo - pad) * 20) / 20), max = Math.ceil((hi + pad) * 20) / 20 || 1;
  const W = WIDE, ih = height - PAD.top - PAD.bottom, step = (W - PAD.left - PAD.right) / weeks.length;
  const pt = (i: number, v: number) => [PAD.left + step * (i + 0.5), PAD.top + ih * (1 - (v - min) / (max - min))] as const;
  const segs: string[] = [];
  let open = false;
  values.forEach((v, i) => {
    if (v === null) { open = false; return; }
    const [x, y] = pt(i, v);
    segs.push(`${open ? "L" : "M"}${x},${y}`);
    open = true;
  });
  const fmt = (n: number) => n.toFixed(2);
  return (
    <Frame height={height} min={min} max={max} fmt={fmt} labels={weeks}>
      {baseline !== null && (
        <g>
          <line x1={PAD.left} x2={W - PAD.right} y1={pt(0, baseline)[1]} y2={pt(0, baseline)[1]} className="ref" />
          <text x={W - PAD.right} y={pt(0, baseline)[1] - 5} textAnchor="end" className="tick">your baseline {fmt(baseline)}</text>
        </g>
      )}
      <path d={segs.join("")} className="line s1" />
      {values.map((v, i) => {
        const x = PAD.left + step * i;
        return (
          <g key={weeks[i]} className="col">
            <title>{v === null ? `${weeks[i]}: no activity` : `${weeks[i]}: waste index ${fmt(v)}`}</title>
            <rect x={x} y={PAD.top} width={step} height={ih} className="hit" />
            {v !== null && <circle cx={pt(i, v)[0]} cy={pt(i, v)[1]} r={4} className="dot s1" />}
          </g>
        );
      })}
    </Frame>
  );
}

/** Horizontal share bars: your value as a bar, an optional comparison value as a tick. */
export function ShareBars({ rows, fmt, compareLabel }:
  { rows: { key: string; label: string; sub?: string; value: number; compare?: number }[]; fmt: (n: number) => string;
    compareLabel?: string }) {
  const max = Math.max(...rows.map((r) => Math.max(r.value, r.compare ?? 0)), 1e-9);
  return (
    <div className="hbars">
      {rows.map((r) => (
        <div key={r.key} className="hbar" title={`${r.label}: ${fmt(r.value)}${r.compare !== undefined ? ` (${compareLabel} ${fmt(r.compare)})` : ""}`}>
          <div className="hbar-label">{r.label}{r.sub && <span className="muted"> · {r.sub}</span>}</div>
          <div className="hbar-track">
            <div className="hbar-fill" style={{ width: `${(r.value / max) * 100}%` }} />
            {r.compare !== undefined && <div className="hbar-tick" style={{ left: `${(r.compare / max) * 100}%` }} />}
          </div>
          <div className="hbar-val">{fmt(r.value)}</div>
        </div>
      ))}
    </div>
  );
}

/** Parts of one whole as a single segmented bar, with every part labelled below (value and share). */
export function SplitBar({ parts, fmt }: { parts: { key: string; label: string; value: number; note?: string }[]; fmt: (n: number) => string }) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  return (
    <div>
      <div className="split">
        {parts.map((p, i) => p.value > 0 && (
          <div key={p.key} className={`split-seg c${i + 1}`} style={{ flexGrow: p.value / total }}
               title={`${p.label}: ${fmt(p.value)} (${((p.value / total) * 100).toFixed(1)}%)`} />
        ))}
      </div>
      <div className="split-legend">
        {parts.map((p, i) => (
          <div key={p.key} className="split-row">
            <i className={`key c${i + 1}`} />
            <span>{p.label}{p.note && <span className="muted"> · {p.note}</span>}</span>
            <b>{fmt(p.value)}</b>
            <span className="muted">{((p.value / total) * 100).toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
