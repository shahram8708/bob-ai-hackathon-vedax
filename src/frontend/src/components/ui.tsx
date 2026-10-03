import { forwardRef, useEffect, useId, useRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Info, Loader2, OctagonAlert, X } from "lucide-react";
import { ApiError } from "@/api/client";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand text-white hover:bg-brand-hover border border-brand disabled:bg-brand/50 disabled:border-transparent",
  secondary: "bg-surface text-ink border border-line-strong hover:bg-sunken disabled:text-ink-3",
  ghost: "text-ink-2 hover:bg-sunken hover:text-ink border border-transparent disabled:text-ink-3",
  danger: "bg-critical text-white border border-critical hover:bg-critical-ink disabled:opacity-50",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, children, className, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded font-medium transition-colors disabled:cursor-not-allowed",
        size === "sm" ? "h-8 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

export function Panel({ title, eyebrow, actions, children, className, bodyClassName, id }: { title?: ReactNode; eyebrow?: string; actions?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string; id?: string }) {
  return (
    <section className={cx("panel", className)} aria-labelledby={title && id ? `${id}-title` : undefined}>
      {(title || actions || eyebrow) && (
        <header className="flex min-h-[48px] items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <div className="min-w-0">
            {eyebrow && <div className="eyebrow">{eyebrow}</div>}
            {title && (
              <h2 id={id ? `${id}-title` : undefined} className="truncate text-[0.9375rem] font-semibold text-ink">
                {title}
              </h2>
            )}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

const TONES = {
  neutral: "bg-sunken text-ink-2 border-line",
  good: "bg-good-soft text-good-ink border-good/30",
  warn: "bg-warn-soft text-warn-ink border-warn/40",
  serious: "bg-serious-soft text-serious-ink border-serious/40",
  critical: "bg-critical-soft text-critical-ink border-critical/30",
  brand: "bg-brand-soft text-brand-ink border-brand/20",
  info: "bg-[#E6EFFB] text-[#1C5CAB] border-[#2A78D6]/25",
} as const;
export type Tone = keyof typeof TONES;

export function Badge({ tone = "neutral", children, icon, className, title }: { tone?: Tone; children: ReactNode; icon?: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-[4px] border px-1.5 py-[1px] text-xs font-medium", TONES[tone], className)}>
      {icon}
      {children}
    </span>
  );
}

export function RuleChip({ code }: { code: string }) {
  const tone: Tone = code === "R8" ? "serious" : code === "R2" ? "critical" : code === "R4" ? "info" : code === "R1" || code === "R7" ? "good" : "neutral";
  return (
    <Badge tone={tone} className="font-mono text-2xs" title={RULES[code]}>
      {code}
    </Badge>
  );
}

export const RULES: Record<string, string> = {
  R1: "Vehicle already meets required SoC — no charging",
  R2: "Urgent departure with insufficient SoC — prioritised immediately",
  R3: "Multiple vehicles competed for a charger — priority + earliest departure",
  R4: "Flexible charging — shifted to lower-cost window",
  R5: "Charger unavailable — reassigned to a compatible charger",
  R6: "Missed reserved slot — released and rescheduled",
  R7: "Target SoC reached — charger freed",
  R8: "Manual emergency override — supersedes normal schedule",
};

export function Field({ label, hint, error, children, required, htmlFor }: { label: string; hint?: string; error?: string; children: ReactNode; required?: boolean; htmlFor?: string }) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-ink-2">
        {label}
        {required && <span className="text-critical"> *</span>}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-critical-ink" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-ink-3">{hint}</p>
      ) : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(function Input({ className, invalid, ...rest }, ref) {
  return <input ref={ref} aria-invalid={invalid || undefined} className={cx("input", className)} {...rest} />;
});

export function Select({ className, invalid, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }) {
  return (
    <select aria-invalid={invalid || undefined} className={cx("input pr-8", className)} {...rest}>
      {children}
    </select>
  );
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cx("input min-h-[84px] resize-y", className)} {...rest} />;
}

export function Toggle({ checked, onChange, label, disabled, description }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean; description?: string }) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <label htmlFor={id} className="text-sm font-medium text-ink">
          {label}
        </label>
        {description && <p className="text-xs text-ink-3">{description}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx("relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors disabled:opacity-50", checked ? "border-brand bg-brand" : "border-line-strong bg-sunken")}
      >
        <span className={cx("absolute left-0 top-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform", checked ? "translate-x-[17px]" : "translate-x-[1px]")} />
      </button>
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-ink-3">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {label}…
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded bg-sunken", className)} aria-hidden />;
}

export function LoadingBlock({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-8" />
      ))}
    </div>
  );
}

export function EmptyState({ title, children, icon, action }: { title: string; children?: ReactNode; icon?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      {icon && <div className="text-ink-3">{icon}</div>}
      <p className="text-sm font-medium text-ink">{title}</p>
      {children && <p className="max-w-sm text-xs text-ink-3">{children}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError ? error.message : "Something went wrong while loading this view.";
  return (
    <div role="alert" className="flex items-start gap-3 rounded border border-critical/30 bg-critical-soft px-4 py-3 text-sm text-critical-ink">
      <OctagonAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="flex-1">
        <p className="font-medium">Couldn’t load data</p>
        <p className="text-xs">{message}</p>
      </div>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function Callout({ tone = "info", title, children, icon }: { tone?: "info" | "warn" | "good" | "critical"; title?: string; children: ReactNode; icon?: ReactNode }) {
  const map = {
    info: ["border-[#2A78D6]/25 bg-[#EEF4FC] text-[#1C4F8F]", <Info key="i" className="h-4 w-4" aria-hidden />],
    warn: ["border-warn/40 bg-warn-soft text-warn-ink", <AlertTriangle key="w" className="h-4 w-4" aria-hidden />],
    good: ["border-good/30 bg-good-soft text-good-ink", <CheckCircle2 key="g" className="h-4 w-4" aria-hidden />],
    critical: ["border-critical/30 bg-critical-soft text-critical-ink", <OctagonAlert key="c" className="h-4 w-4" aria-hidden />],
  } as const;
  const [cls, ico] = map[tone];
  return (
    <div className={cx("flex gap-2.5 rounded border px-3 py-2.5 text-sm", cls)}>
      <span className="mt-0.5 shrink-0">{icon ?? ico}</span>
      <div>
        {title && <p className="font-medium">{title}</p>}
        <div className="text-[0.8125rem] leading-relaxed">{children}</div>
      </div>
    </div>
  );
}

export function SocBar({ soc, target, required, size = "md", showLabel = true }: { soc: number; target?: number | null; required?: number | null; size?: "sm" | "md"; showLabel?: boolean }) {
  const req = required ?? target ?? null;
  const tone = req === null ? "bg-ink-2" : soc >= req - 0.5 ? "bg-good" : soc < 20 ? "bg-critical" : "bg-warn";
  return (
    <div className="flex items-center gap-2" aria-label={`State of charge ${Math.round(soc)}%${req !== null ? `, required ${Math.round(req)}%` : ""}`} role="img">
      <div className={cx("relative w-full min-w-[64px] overflow-hidden rounded-[3px] bg-sunken", size === "sm" ? "h-1.5" : "h-2.5")}>
        <div className={cx("absolute inset-y-0 left-0 rounded-[3px]", tone)} style={{ width: `${Math.max(0, Math.min(100, soc))}%` }} />
        {req !== null && <div className="absolute inset-y-[-2px] w-[2px] bg-ink" style={{ left: `calc(${Math.min(100, req)}% - 1px)` }} title={`Required ${Math.round(req)}%`} />}
      </div>
      {showLabel && <span className="num w-9 shrink-0 text-right text-xs text-ink">{Math.round(soc)}%</span>}
    </div>
  );
}

export function Kpi({ label, value, sub, tone, icon }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "good" | "warn" | "critical" | "brand"; icon?: ReactNode }) {
  const accent = tone === "good" ? "text-good-ink" : tone === "warn" ? "text-warn-ink" : tone === "critical" ? "text-critical-ink" : tone === "brand" ? "text-brand" : "text-ink";
  return (
    <div className="panel flex flex-col justify-between gap-1 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="eyebrow">{label}</span>
        {icon && <span className="text-ink-3">{icon}</span>}
      </div>
      <div className={cx("num text-[1.625rem] font-medium leading-tight", accent)}>{value}</div>
      {sub && <div className="text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

function useFocusTrap(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const focusables = () => Array.from(node?.querySelectorAll<HTMLElement>('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])') ?? []).filter((el) => !el.hasAttribute("disabled"));
    (focusables()[1] ?? focusables()[0])?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const els = focusables();
        if (!els.length) return;
        const first = els[0];
        const last = els[els.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      previous?.focus();
    };
  }, [open, onClose]);
  return ref;
}

export function Modal({ open, onClose, title, description, children, footer, width = "max-w-lg" }: { open: boolean; onClose: () => void; title: string; description?: ReactNode; children: ReactNode; footer?: ReactNode; width?: string }) {
  const ref = useFocusTrap(open, onClose);
  const id = useId();
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/40 p-0 sm:items-center sm:p-6" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={id} className={cx("flex max-h-[92vh] w-full flex-col rounded-t-lg border border-line bg-surface shadow-pop sm:rounded-lg", width)}>
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            <h2 id={id} className="text-base font-semibold">
              {title}
            </h2>
            {description && <p className="mt-0.5 text-xs text-ink-3">{description}</p>}
          </div>
          <button onClick={onClose} className="rounded p-1 text-ink-3 hover:bg-sunken hover:text-ink" aria-label="Close dialog">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="scroll-thin overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({ open, onClose, title, subtitle, children, footer }: { open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  const ref = useFocusTrap(open, onClose);
  const id = useId();
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-40 flex justify-end bg-ink/30" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside ref={ref} role="dialog" aria-modal="true" aria-labelledby={id} className="flex h-full w-full max-w-[520px] animate-slidein flex-col border-l border-line bg-surface shadow-pop">
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 id={id} className="truncate text-base font-semibold">
              {title}
            </h2>
            {subtitle && <div className="mt-0.5 text-xs text-ink-3">{subtitle}</div>}
          </div>
          <button onClick={onClose} className="rounded p-1 text-ink-3 hover:bg-sunken hover:text-ink" aria-label="Close panel">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="scroll-thin flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </aside>
    </div>,
    document.body,
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between gap-3 border-t border-line px-3 py-2 text-xs text-ink-3">
      <span className="num">
        {total === 0 ? "0" : `${(page - 1) * pageSize + 1}–${Math.min(total, page * pageSize)}`} of {total}
      </span>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page" icon={<ChevronLeft className="h-3.5 w-3.5" />} />
        <span className="num px-1">
          {page} / {pages}
        </span>
        <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page" icon={<ChevronRight className="h-3.5 w-3.5" />} />
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items, label }: { value: T; onChange: (v: T) => void; items: { value: T; label: ReactNode; count?: number }[]; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="scroll-thin flex gap-1 overflow-x-auto border-b border-line">
      {items.map((it) => (
        <button
          key={it.value}
          role="tab"
          aria-selected={value === it.value}
          onClick={() => onChange(it.value)}
          className={cx(
            "-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors",
            value === it.value ? "border-brand font-medium text-ink" : "border-transparent text-ink-3 hover:text-ink",
          )}
        >
          {it.label}
          {it.count !== undefined && <span className="num rounded bg-sunken px-1 text-2xs text-ink-2">{it.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-xl font-semibold text-ink sm:text-[1.375rem]">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function SimulatedTag() {
  return (
    <Badge tone="neutral" className="font-mono text-2xs uppercase tracking-wide" title="Values come from simulated charger telemetry and the configurable tariff table, not measured fleet data.">
      Simulated data
    </Badge>
  );
}

export function DefinitionList({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,40%)_1fr] gap-x-3 gap-y-2 text-sm">
      {items.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-ink-3">{k}</dt>
          <dd className="min-w-0 text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
