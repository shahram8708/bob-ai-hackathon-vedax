import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "@/api/client";
import type { AuditEntry, Page } from "@/api/types";
import { Badge, EmptyState, ErrorState, Input, LoadingBlock, PageHeader, Pagination, Panel, Select } from "@/components/ui";
import { dateTime, humanize } from "@/lib/format";

const TONE: Record<string, "critical" | "warn" | "info" | "brand" | "neutral" | "serious"> = {
  override: "serious",
  schedule: "brand",
  exception: "critical",
  config: "info",
  charger: "warn",
  auth: "neutral",
};

export default function Audit() {
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search), 300);
    return () => window.clearTimeout(t);
  }, [search]);
  useEffect(() => setPage(1), [category, debounced]);
  const q = useQuery({
    queryKey: ["audit", category, debounced, page],
    queryFn: () => api.get<Page<AuditEntry> & { categories: string[] }>("/audit-logs", { category, search: debounced, page, page_size: 40 }),
    placeholderData: (p) => p,
  });

  return (
    <div>
      <PageHeader title="Audit log" description="Sign-ins, manual overrides, schedule changes, configuration changes, charger-state changes and critical exceptions — append-only." />
      <Panel bodyClassName="p-0">
        <div className="flex flex-col gap-3 border-b border-line p-3 sm:flex-row">
          <div className="relative w-full sm:max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-ink-3" aria-hidden />
            <Input aria-label="Search audit log" placeholder="Search summary, actor or action" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-8" />
          </div>
          <Select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)} className="sm:w-48">
            <option value="">All categories</option>
            {(q.data?.categories ?? []).map((c) => (
              <option key={c} value={c}>
                {humanize(c)}
              </option>
            ))}
          </Select>
        </div>
        {q.isLoading ? (
          <div className="p-4">
            <LoadingBlock rows={10} />
          </div>
        ) : q.error ? (
          <div className="p-4">
            <ErrorState error={q.error} onRetry={() => q.refetch()} />
          </div>
        ) : !q.data?.items.length ? (
          <EmptyState title="No entries match" />
        ) : (
          <>
            <div className="scroll-thin overflow-x-auto">
              <table className="table-base min-w-[900px]">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Category</th>
                    <th>Actor</th>
                    <th>Action</th>
                    <th className="w-1/2">Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {q.data.items.map((a) => (
                    <tr key={a.id} className="cursor-pointer align-top" onClick={() => setOpen(open === a.id ? null : a.id)}>
                      <td className="num whitespace-nowrap text-xs">{dateTime(a.created_at)}</td>
                      <td>
                        <Badge tone={TONE[a.category] ?? "neutral"}>{humanize(a.category)}</Badge>
                      </td>
                      <td className="text-xs">{a.actor}</td>
                      <td className="font-mono text-2xs text-ink-2">{a.action}</td>
                      <td className="text-sm">
                        {a.summary}
                        {open === a.id && Object.keys(a.details ?? {}).length > 0 && <pre className="scroll-thin mt-2 max-h-48 overflow-auto rounded bg-sunken p-2 font-mono text-2xs text-ink-2">{JSON.stringify(a.details, null, 2)}</pre>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={40} total={q.data.total} onPage={setPage} />
          </>
        )}
      </Panel>
    </div>
  );
}
