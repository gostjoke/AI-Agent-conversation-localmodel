// localStorage helpers (safe). 本機儲存（含例外保護）。
export const load = (k, d) => {
  try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; }
};
export const save = (k, v) => {
  try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* quota / private mode */ }
};
export const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
