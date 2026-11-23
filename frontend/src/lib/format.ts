// A fixed locale keeps chart axes and tables consistent with the model-written answers
// (which use "1.2M" and "406,131"); the browser default would give e.g. "12.3L" in en-IN.
const LOCALE = "en-US";
const compact = new Intl.NumberFormat(LOCALE, { notation: "compact", maximumFractionDigits: 1 });
const full = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 2 });

export function formatNumber(v: unknown, mode: "full" | "compact" = "full"): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return v == null ? "" : String(v);
  if (mode === "compact" && Math.abs(v) >= 10_000) return compact.format(v);
  return full.format(v);
}

export function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return formatNumber(v);
  if (typeof v === "boolean") return v ? "true" : "false";
  const s = String(v);
  // ISO timestamps at midnight read better as plain dates.
  const midnight = s.match(/^(\d{4}-\d{2}-\d{2})[T ]00:00:00(\.0+)?$/);
  return midnight ? midnight[1] : s;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

export function relativeTime(iso: string): string {
  const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime();
  const mins = Math.round((Date.now() - then) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  const days = Math.round(hrs / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

export const TYPE_LABEL: Record<string, string> = {
  integer: "whole number",
  number: "number",
  text: "text",
  datetime: "date",
  boolean: "yes/no",
};
