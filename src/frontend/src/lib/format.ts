let fleetTz = "UTC";
let fleetCurrency = "USD";

export function setFleetLocale(tz: string, currency: string) {
  fleetTz = tz;
  fleetCurrency = currency;
}

export function getFleetTz() {
  return fleetTz;
}

const cache = new Map<string, Intl.DateTimeFormat>();
function fmt(opts: Intl.DateTimeFormatOptions) {
  const key = fleetTz + JSON.stringify(opts);
  let f = cache.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat("en-GB", { timeZone: fleetTz, ...opts });
    cache.set(key, f);
  }
  return f;
}

export function toDate(v: string | Date | null | undefined): Date | null {
  if (!v) return null;
  const d = v instanceof Date ? v : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function time(v: string | Date | null | undefined) {
  const d = toDate(v);
  return d ? fmt({ hour: "2-digit", minute: "2-digit", hour12: false }).format(d) : "—";
}

export function dayTime(v: string | Date | null | undefined) {
  const d = toDate(v);
  if (!d) return "—";
  const today = fmt({ year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  const that = fmt({ year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  if (today === that) return `Today ${time(d)}`;
  const tomorrow = fmt({ year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(Date.now() + 86400000));
  if (tomorrow === that) return `Tomorrow ${time(d)}`;
  return fmt({ day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }).format(d);
}

export function date(v: string | Date | null | undefined) {
  const d = toDate(v);
  return d ? fmt({ day: "2-digit", month: "short", year: "numeric" }).format(d) : "—";
}

export function dateTime(v: string | Date | null | undefined) {
  const d = toDate(v);
  return d ? fmt({ day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(d) : "—";
}

export function relative(v: string | Date | null | undefined, now = Date.now()) {
  const d = toDate(v);
  if (!d) return "—";
  const diff = Math.round((d.getTime() - now) / 60000);
  const abs = Math.abs(diff);
  const text = abs < 1 ? "now" : abs < 60 ? `${abs} min` : abs < 48 * 60 ? `${Math.floor(abs / 60)} h ${abs % 60 ? `${abs % 60} m` : ""}`.trim() : `${Math.round(abs / 1440)} d`;
  if (text === "now") return "now";
  return diff > 0 ? `in ${text}` : `${text} ago`;
}

export function money(v: number | null | undefined, digits = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: fleetCurrency, maximumFractionDigits: digits, minimumFractionDigits: digits }).format(v);
}

export function rate(v: number | null | undefined) {
  if (v === null || v === undefined) return "—";
  return `${money(v, 2)}/kWh`;
}

export function num(v: number | null | undefined, digits = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(v);
}

export function pct(v: number | null | undefined, digits = 0) {
  return v === null || v === undefined ? "—" : `${num(v, digits)}%`;
}

export function kwh(v: number | null | undefined, digits = 1) {
  return v === null || v === undefined ? "—" : `${num(v, digits)} kWh`;
}

export function humanize(v: string | null | undefined) {
  if (!v) return "—";
  const s = v.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function localInputValue(d: Date) {
  const parts = fmt({ year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour") === "24" ? "00" : get("hour")}:${get("minute")}`;
}

export function fromLocalInput(value: string): string {
  const [datePart, timePart] = value.split("T");
  const [y, m, d] = datePart.split("-").map(Number);
  const [hh, mm] = timePart.split(":").map(Number);
  const guess = Date.UTC(y, m - 1, d, hh, mm);
  const asLocal = localInputValue(new Date(guess));
  const [gd, gt] = asLocal.split("T");
  const [gy, gm, gday] = gd.split("-").map(Number);
  const [gh, gmin] = gt.split(":").map(Number);
  const offset = Date.UTC(gy, gm - 1, gday, gh, gmin) - guess;
  return new Date(guess - offset).toISOString();
}

export const TARIFF_COLORS: Record<string, string> = {
  off_peak: "#2A78D6",
  shoulder: "#1BAF7A",
  peak: "#EB6834",
  custom: "#4A3AA7",
};

export const TARIFF_LABEL: Record<string, string> = {
  off_peak: "Off-peak",
  shoulder: "Shoulder",
  peak: "Peak",
  custom: "Custom",
};
