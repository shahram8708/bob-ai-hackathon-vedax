import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { CheckCircle2, OctagonAlert, Info, X } from "lucide-react";
import { ApiError } from "@/api/client";
import { cx } from "@/components/ui";

type ToastTone = "success" | "error" | "info";
interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  body?: string;
}

const ToastContext = createContext<{ push: (t: Omit<Toast, "id">) => void; error: (e: unknown, title?: string) => void } | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const push = useCallback(
    (t: Omit<Toast, "id">) => {
      const id = Date.now() + Math.random();
      setToasts((list) => [...list.slice(-3), { ...t, id }]);
      window.setTimeout(() => dismiss(id), t.tone === "error" ? 7000 : 4500);
    },
    [dismiss],
  );
  const error = useCallback(
    (e: unknown, title = "Action failed") => {
      const body = e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ? `${e.message}: ${Object.values(e.fieldErrors())[0]}` : e.message) : "Unexpected error";
      push({ tone: "error", title, body });
    },
    [push],
  );
  return (
    <ToastContext.Provider value={{ push, error }}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} role={t.tone === "error" ? "alert" : "status"} className={cx("pointer-events-auto flex animate-slidein items-start gap-2.5 rounded border bg-surface px-3.5 py-3 shadow-pop", t.tone === "error" ? "border-critical/40" : t.tone === "success" ? "border-good/40" : "border-line")}>
            {t.tone === "success" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-good-ink" aria-hidden /> : t.tone === "error" ? <OctagonAlert className="mt-0.5 h-4 w-4 shrink-0 text-critical" aria-hidden /> : <Info className="mt-0.5 h-4 w-4 shrink-0 text-[#2A78D6]" aria-hidden />}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-ink">{t.title}</p>
              {t.body && <p className="mt-0.5 text-xs text-ink-2">{t.body}</p>}
            </div>
            <button onClick={() => dismiss(t.id)} className="rounded p-0.5 text-ink-3 hover:text-ink" aria-label="Dismiss notification">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}
