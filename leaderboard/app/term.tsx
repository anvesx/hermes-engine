// Terminal-look building blocks shared by the owner's dashboard (/u/<handle>) and /admin. Server-rendered, no client JS.
import type { ReactNode } from "react";

// 3x5 pixel glyphs
const GLYPHS: Record<string, string[]> = {
  "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"],
  "2": ["111", "001", "111", "100", "111"], "3": ["111", "001", "111", "001", "111"],
  "4": ["101", "101", "111", "001", "001"], "5": ["111", "100", "111", "001", "111"],
  "6": ["111", "100", "111", "101", "111"], "7": ["111", "001", "001", "001", "001"],
  "8": ["111", "101", "111", "101", "111"], "9": ["111", "101", "111", "001", "111"],
  ".": ["0", "0", "0", "0", "1"], ",": ["0", "0", "0", "1", "1"], k: ["101", "101", "110", "101", "101"],
  B: ["110", "101", "110", "101", "110"], M: ["10001", "11011", "10101", "10001", "10001"],
  $: ["011", "110", "010", "011", "110"], h: ["100", "100", "110", "101", "101"],
};

/** Big text as a 5-row pixel grid. Drawn with cells, not block characters, which most web font subsets lack. */
export function Figlet({ text }: { text: string }) {
  const chars = [...text].filter((c) => GLYPHS[c]);
  const rows = [0, 1, 2, 3, 4].map((r) => chars.map((c) => GLYPHS[c][r]).join("0"));
  return (
    <div className="figlet" role="img" aria-label={text} style={{ gridTemplateColumns: `repeat(${rows[0].length}, var(--px))` }}>
      {rows.flatMap((row, r) => [...row].map((on, c) => <i key={`${r}-${c}`} className={on === "1" ? "on" : ""} />))}
    </div>
  );
}

/** A segmented progress bar, the web version of ██████░░░░. */
export function SegBar({ f, n = 10 }: { f: number; n?: number }) {
  const on = Math.max(0, Math.min(n, Math.round(f * n)));
  return <span className="segbar" aria-hidden>{Array.from({ length: n }, (_, i) => <i key={i} className={i < on ? "on" : ""} />)}</span>;
}

/** Terminal bar chart: scanline-filled bars on a 0 / half / peak axis, the latest bar highlighted. Hover shows the value. */
export function TermBars({ title, labels, values, fmt, tick, every = 7 }:
  { title: ReactNode; labels: string[]; values: number[]; fmt: (n: number) => string; tick: (k: string) => string; every?: number }) {
  const peak = Math.max(...values, 1);
  return (
    <div className="term-chart">
      <div className="tc-head"><span>{title}</span><span className="dim">peak {fmt(peak)}</span></div>
      <div className="tc-plot">
        <div className="tc-axis"><span>{fmt(peak)}</span><span>{fmt(peak / 2)}</span><span>0</span></div>
        <div className="tc-bars">
          {values.map((v, i) => (
            <i key={labels[i]} title={`${tick(labels[i])}: ${fmt(v)}`}
               className={i === values.length - 1 ? "now" : v === 0 ? "off" : ""}
               style={{ height: `${Math.max(2, (v / peak) * 100)}%` }} />
          ))}
        </div>
      </div>
      <div className="tc-x" style={{ gridTemplateColumns: `repeat(${labels.length}, 1fr)` }}>
        {labels.map((k, i) => <span key={k}>{(labels.length - 1 - i) % every === 0 ? tick(k) : ""}</span>)}
      </div>
    </div>
  );
}

/** The window chrome: traffic lights, a centred title, a right-hand note, the body and an optional key-hint footer. */
export function TermWindow({ title, note, foot, children, label }:
  { title: string; note: string; foot?: ReactNode; children: ReactNode; label: string }) {
  return (
    <section className="term" aria-label={label}>
      <div className="term-bar"><span className="dots"><i /><i /><i /></span><span>{title}</span><span>{note}</span></div>
      <div className="term-body">{children}</div>
      {foot && <div className="term-foot">{foot}</div>}
    </section>
  );
}
