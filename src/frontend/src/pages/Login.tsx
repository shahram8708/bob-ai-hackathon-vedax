import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "@/api/client";
import { Logo } from "@/components/Layout";
import { Button, Field, Input } from "@/components/ui";
import { useSession } from "@/lib/session";

function LoadShiftArt() {
  const hours = Array.from({ length: 24 }, (_, h) => h);
  const band = (h: number) => (h < 6 ? "#2A78D6" : h >= 18 && h < 22 ? "#EB6834" : "#1BAF7A");
  const before = [2, 2, 1, 1, 1, 2, 4, 6, 5, 4, 4, 5, 6, 7, 9, 12, 16, 22, 30, 34, 31, 24, 12, 5];
  const after = [26, 30, 31, 29, 24, 14, 6, 5, 5, 4, 4, 5, 6, 6, 7, 8, 9, 8, 4, 3, 3, 4, 10, 18];
  const x = (h: number) => 12 + h * 15;
  const y = (v: number) => 150 - v * 3.4;
  const path = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${x(i) + 7.5},${y(v)}`).join(" ");
  return (
    <svg viewBox="0 0 384 190" className="w-full" role="img" aria-label="Illustration: charging load moved from the evening peak into the overnight off-peak window">
      {hours.map((h) => (
        <rect key={h} x={x(h)} y={156} width={14} height={5} rx={1} fill={band(h)} opacity={0.9} />
      ))}
      <path d={path(before)} fill="none" stroke="#F4F2ED" strokeOpacity={0.35} strokeWidth={2} strokeDasharray="4 4" />
      <path d={path(after)} fill="none" stroke="#C9E86A" strokeWidth={2.5} strokeLinejoin="round" />
      {[0, 6, 12, 18].map((h) => (
        <text key={h} x={x(h)} y={178} fill="#F4F2ED" fillOpacity={0.55} fontSize={9} fontFamily="IBM Plex Mono">
          {String(h).padStart(2, "0")}:00
        </text>
      ))}
    </svg>
  );
}

export function LoginPage() {
  const { login } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : "/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <div className="relative hidden flex-col justify-between overflow-hidden bg-brand-ink p-10 text-paper lg:flex">
        <div className="flex items-center gap-2">
          <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden>
            <rect width="32" height="32" rx="7" fill="#F4F2ED" />
            <path d="M9 9h9a5 5 0 0 1 0 10h-4" fill="none" stroke="#1F4D3A" strokeWidth="3" strokeLinecap="round" />
            <path d="M17 15l-4 4 4 4" fill="none" stroke="#5E8F2A" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="text-lg font-semibold tracking-tight">ChargeOpt</span>
        </div>
        <div className="max-w-md">
          <p className="font-mono text-2xs uppercase tracking-[0.16em] text-volt">Rule-based fleet charging</p>
          <h1 className="mt-3 text-[2rem] font-semibold leading-[1.15] tracking-tight">Every vehicle ready for departure. Every kilowatt-hour in the cheapest window that allows it.</h1>
          <p className="mt-4 text-sm leading-relaxed text-paper/70">
            ChargeOpt coordinates state of charge, trip deadlines, charger capacity and tariff windows with transparent, deterministic rules — and explains each decision it makes.
          </p>
        </div>
        <div>
          <LoadShiftArt />
          <div className="mt-2 flex gap-4 font-mono text-2xs uppercase tracking-wider text-paper/60">
            <span>
              <span className="mr-1.5 inline-block h-0.5 w-4 bg-paper/40 align-middle" />
              Unmanaged load
            </span>
            <span>
              <span className="mr-1.5 inline-block h-0.5 w-4 bg-volt align-middle" />
              Rule-based schedule
            </span>
          </div>
        </div>
      </div>
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <Logo className="mb-10 lg:hidden" />
          <h2 className="text-xl font-semibold">Sign in</h2>
          <p className="mt-1 text-sm text-ink-3">Use your ChargeOpt account. Access is limited to the permissions of your role.</p>
          <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
            <Field label="Email" htmlFor="email">
              <Input id="email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} invalid={!!error && !email} autoFocus />
            </Field>
            <Field label="Password" htmlFor="password">
              <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} invalid={!!error && !password} />
            </Field>
            {error && (
              <p role="alert" className="rounded border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical-ink">
                {error}
              </p>
            )}
            <Button type="submit" variant="primary" className="w-full" loading={busy}>
              Sign in
            </Button>
          </form>
          <p className="mt-8 text-xs text-ink-3">Sessions use a secure HTTP-only cookie and expire automatically. Sign-ins are recorded in the audit log.</p>
        </div>
      </div>
    </div>
  );
}
