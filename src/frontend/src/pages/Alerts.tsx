import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellOff, CheckCheck, Eye, Plus } from "lucide-react";
import { api } from "@/api/client";
import type { Alert, Page } from "@/api/types";
import { SeverityBadge } from "@/components/status";
import { Badge, Button, EmptyState, ErrorState, Field, Input, LoadingBlock, Modal, PageHeader, Pagination, Panel, Select, Tabs, Textarea } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useSession } from "@/lib/session";
import { dateTime, dayTime, humanize, relative } from "@/lib/format";

type StatusFilter = "active" | "open" | "acknowledged" | "resolved" | "all";
const TYPES = ["below_required_soc", "departed_below_required", "session_interrupted", "charger_fault", "missed_slot", "reservation_conflict", "unexpected_consumption", "peak_approaching", "readiness_below_threshold", "manual_exception"];

function ActionModal({ alert, mode, onClose }: { alert: Alert; mode: "ack" | "resolve"; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [note, setNote] = useState("");
  const invalid = mode === "resolve" && note.trim().length < 3;
  const m = useMutation({
    mutationFn: () => api.post(`/alerts/${alert.id}/${mode === "ack" ? "acknowledge" : "resolve"}`, { note }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alerts"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.push({ tone: "success", title: mode === "ack" ? "Alert acknowledged" : "Alert resolved" });
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={mode === "ack" ? "Acknowledge alert" : "Resolve alert"}
      description={alert.title}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={invalid} loading={m.isPending} onClick={() => m.mutate()}>
            {mode === "ack" ? "Acknowledge" : "Resolve"}
          </Button>
        </>
      }
    >
      <Field label={mode === "ack" ? "Note (optional)" : "Resolution — what was done?"} htmlFor="al-note" error={invalid && note ? "At least 3 characters" : undefined} required={mode === "resolve"}>
        <Textarea id="al-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder={mode === "ack" ? "e.g. Technician dispatched" : "e.g. Vehicle moved to PNY-C07, charging resumed"} />
      </Field>
    </Modal>
  );
}

function NewAlert({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState({ severity: "warning", title: "", message: "" });
  const valid = f.title.trim().length >= 4 && f.message.trim().length >= 4;
  const m = useMutation({
    mutationFn: () => api.post("/alerts", f),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alerts"] });
      toast.push({ tone: "success", title: "Exception recorded" });
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal
      open
      onClose={onClose}
      title="Record an operational exception"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!valid} loading={m.isPending} onClick={() => m.mutate()}>
            Record
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Severity" htmlFor="na-s">
          <Select id="na-s" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })}>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </Select>
        </Field>
        <Field label="Title" htmlFor="na-t" required>
          <Input id="na-t" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} maxLength={200} />
        </Field>
        <Field label="Details" htmlFor="na-m" required>
          <Textarea id="na-m" value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} />
        </Field>
      </div>
    </Modal>
  );
}

export default function Alerts() {
  const { can } = useSession();
  const [status, setStatus] = useState<StatusFilter>("active");
  const [type, setType] = useState("");
  const [severity, setSeverity] = useState("");
  const [page, setPage] = useState(1);
  const [action, setAction] = useState<{ alert: Alert; mode: "ack" | "resolve" } | null>(null);
  const [creating, setCreating] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);
  const q = useQuery({
    queryKey: ["alerts", status, type, severity, page],
    queryFn: () => api.get<Page<Alert> & { counts: Record<string, number> }>("/alerts", { status, type, severity, page, page_size: 25 }),
    placeholderData: (p) => p,
    refetchInterval: 15_000,
  });
  const counts = q.data?.counts ?? {};

  return (
    <div>
      <PageHeader
        title="Alerts & exceptions"
        description="Operational exceptions raised by the monitoring rules. Acknowledge to take ownership; resolve with a note to close the record."
        actions={
          can("alerts:manage") && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
              Record exception
            </Button>
          )
        }
      />
      <Panel bodyClassName="p-0">
        <div className="flex min-w-0 flex-col gap-3 border-b border-line p-3 lg:flex-row lg:items-center lg:justify-between">
          <Tabs<StatusFilter>
            label="Alert status"
            value={status}
            onChange={(v) => {
              setStatus(v);
              setPage(1);
            }}
            items={[
              { value: "active", label: "Active", count: (counts.open ?? 0) + (counts.acknowledged ?? 0) },
              { value: "open", label: "Open", count: counts.open ?? 0 },
              { value: "acknowledged", label: "Acknowledged", count: counts.acknowledged ?? 0 },
              { value: "resolved", label: "Resolved", count: counts.resolved ?? 0 },
              { value: "all", label: "All" },
            ]}
          />
          <div className="flex min-w-0 gap-2">
            <Select aria-label="Filter by type" value={type} onChange={(e) => { setType(e.target.value); setPage(1); }} className="min-w-0 flex-1 lg:w-auto">
              <option value="">All types</option>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {humanize(t)}
                </option>
              ))}
            </Select>
            <Select aria-label="Filter by severity" value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(1); }} className="min-w-0 flex-1 lg:w-auto">
              <option value="">All severities</option>
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </Select>
          </div>
        </div>
        {q.isLoading ? (
          <div className="p-4">
            <LoadingBlock rows={8} />
          </div>
        ) : q.error ? (
          <div className="p-4">
            <ErrorState error={q.error} onRetry={() => q.refetch()} />
          </div>
        ) : !q.data?.items.length ? (
          <EmptyState title="Nothing here" icon={<BellOff className="h-6 w-6" />}>
            No alerts match the current filters.
          </EmptyState>
        ) : (
          <>
            <ul className="divide-y divide-line">
              {q.data.items.map((a) => (
                <li key={a.id} className="px-4 py-3">
                  <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                    <button className="flex min-w-0 flex-1 items-start gap-3 text-left" onClick={() => setExpanded(expanded === a.id ? null : a.id)} aria-expanded={expanded === a.id}>
                      <SeverityBadge value={a.severity} />
                      <div className="min-w-0">
                        <p className="font-medium leading-snug">{a.title}</p>
                        <p className="mt-0.5 text-xs text-ink-3">
                          {humanize(a.type)} · {dayTime(a.created_at)} ({relative(a.created_at)})
                          {a.vehicle && (
                            <>
                              {" · "}
                              <Link to={`/vehicles/${a.vehicle_id}`} className="num text-brand hover:underline" onClick={(e) => e.stopPropagation()}>
                                {a.vehicle}
                              </Link>
                            </>
                          )}
                          {a.charger && <> · {a.charger}</>}
                        </p>
                        {expanded === a.id && (
                          <div className="mt-2 space-y-1.5 text-sm text-ink-2">
                            <p>{a.message}</p>
                            {a.acknowledged_at && <p className="text-xs text-ink-3">Acknowledged {dateTime(a.acknowledged_at)}</p>}
                            {a.resolved_at && (
                              <p className="text-xs text-ink-3">
                                Resolved {dateTime(a.resolved_at)} — {a.resolution_note}
                              </p>
                            )}
                          </div>
                        )}
                      </div>
                    </button>
                    <div className="flex shrink-0 items-center gap-2 pl-8 md:pl-0">
                      <Badge tone={a.status === "open" ? "critical" : a.status === "acknowledged" ? "warn" : "good"}>{humanize(a.status)}</Badge>
                      {can("alerts:manage") && a.status === "open" && (
                        <Button size="sm" icon={<Eye className="h-3.5 w-3.5" />} onClick={() => setAction({ alert: a, mode: "ack" })}>
                          Acknowledge
                        </Button>
                      )}
                      {can("alerts:manage") && a.status !== "resolved" && (
                        <Button size="sm" variant="primary" icon={<CheckCheck className="h-3.5 w-3.5" />} onClick={() => setAction({ alert: a, mode: "resolve" })}>
                          Resolve
                        </Button>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
            <Pagination page={page} pageSize={25} total={q.data.total} onPage={setPage} />
          </>
        )}
      </Panel>
      {action && <ActionModal alert={action.alert} mode={action.mode} onClose={() => setAction(null)} />}
      {creating && <NewAlert onClose={() => setCreating(false)} />}
    </div>
  );
}
