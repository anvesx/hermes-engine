export const compact = (n: number) =>
  n >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : `${Math.round(n)}`;
export const money = (n: number) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
export const hours = (n: number) => `${n.toLocaleString("en-US", { maximumFractionDigits: 1 })}h`;
export const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
