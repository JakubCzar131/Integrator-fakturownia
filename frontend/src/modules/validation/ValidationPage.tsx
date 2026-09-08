import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { ISSUE_TYPE_LABELS, formatDateTime, formatDuration } from "../../lib/format";
import type { Page, ValidationIssue, ValidationRun } from "../../lib/types";
import { usePagedData } from "../../lib/usePagedData";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { DetailTabs } from "../../components/erp/DetailTabs";
import { FilterBar, FilterField } from "../../components/erp/FilterBar";
import { StatusBadge } from "../../components/erp/StatusBadge";
import { useToast } from "../../components/erp/Toast";
import { ValidationPanel } from "../../components/erp/ValidationPanel";
import { useGridState } from "../../components/datagrid/DataGrid";

const STATUS_FILTER_OPTIONS = [
  "ERROR", "WARNING", "NEEDS_MAPPING", "NEEDS_OPENING_BALANCE", "IGNORED", "RESOLVED",
];

function RunsHistory() {
  const [runs, setRuns] = useState<ValidationRun[]>([]);
  useEffect(() => {
    api.get<Page<ValidationRun>>("/validation/runs?per_page=50")
      .then((page) => setRuns(page.items)).catch(() => undefined);
  }, []);
  return (
    <table className="datagrid">
      <thead>
        <tr>
          <th>#</th><th>Status</th><th>Start</th><th>Czas</th>
          <th className="num">Faktury</th><th className="num">Pozycje</th>
          <th className="num">Nowe problemy</th><th className="num">Zamknięte auto</th><th>Komunikat</th>
        </tr>
      </thead>
      <tbody>
        {runs.length === 0 && <tr className="empty-row"><td colSpan={9}>Brak uruchomień</td></tr>}
        {runs.map((run) => (
          <tr key={run.id}>
            <td>{run.id}</td>
            <td><StatusBadge value={run.status} /></td>
            <td>{formatDateTime(run.started_at)}</td>
            <td>{formatDuration(run.duration_seconds)}</td>
            <td className="num">{run.invoices_checked}</td>
            <td className="num">{run.positions_checked}</td>
            <td className="num">{run.issues_created}</td>
            <td className="num">{run.issues_auto_resolved}</td>
            <td>{run.message ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ValidationPage() {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [searchParams] = useSearchParams();
  const [gridState, setGridState] = useGridState({ perPage: 25 });
  const [status, setStatus] = useState(
    searchParams.get("status") ?? "ERROR,WARNING,NEEDS_MAPPING,NEEDS_OPENING_BALANCE",
  );
  const [issueType, setIssueType] = useState(searchParams.get("issue_type") ?? "");
  const [search, setSearch] = useState("");

  const { data, loading, reload } = usePagedData<ValidationIssue>("/validation/issues", gridState, {
    status: status || undefined,
    issue_type: issueType || undefined,
    search: search || undefined,
  });

  const runValidation = async () => {
    try {
      const run = await api.post<{ message: string | null }>("/validation/run");
      toast.success(run.message ?? "Walidacja zakończona");
      reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd walidacji");
    }
  };

  const issuesContent = (
    <div>
      <FilterBar>
        <FilterField label="Status">
          <select value={status} onChange={(e) => { setStatus(e.target.value); setGridState({ ...gridState, page: 1 }); }}>
            <option value="ERROR,WARNING,NEEDS_MAPPING,NEEDS_OPENING_BALANCE">Otwarte (wszystkie)</option>
            {STATUS_FILTER_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            <option value="">— wszystkie —</option>
          </select>
        </FilterField>
        <FilterField label="Typ problemu">
          <select value={issueType} onChange={(e) => { setIssueType(e.target.value); setGridState({ ...gridState, page: 1 }); }}>
            <option value="">— wszystkie —</option>
            {Object.entries(ISSUE_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label="Szukaj (faktura / produkt / opis)">
          <input value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 240 }} />
        </FilterField>
        <span style={{ flex: 1 }} />
        <span className="text-muted">Znaleziono: {data?.total ?? 0}</span>
      </FilterBar>
      {loading ? (
        <p className="text-muted">Ładowanie…</p>
      ) : (
        <>
          <ValidationPanel issues={data?.items ?? []} onChanged={reload} />
          <div className="datagrid-footer" style={{ border: "1px solid var(--c-border)" }}>
            <button className="btn btn--small" disabled={gridState.page <= 1}
              onClick={() => setGridState({ ...gridState, page: gridState.page - 1 })}>‹ Poprzednia</button>
            <span>str. {gridState.page} / {data?.pages ?? 1}</span>
            <button className="btn btn--small" disabled={gridState.page >= (data?.pages ?? 1)}
              onClick={() => setGridState({ ...gridState, page: gridState.page + 1 })}>Następna ›</button>
          </div>
        </>
      )}
    </div>
  );

  return (
    <div>
      <ActionToolbar title="Walidacje sprzedaży">
        {canWrite && (
          <button className="btn btn--primary" onClick={runValidation}>✓ Uruchom walidację</button>
        )}
      </ActionToolbar>
      <DetailTabs
        tabs={[
          { key: "issues", label: "Problemy", content: issuesContent },
          { key: "runs", label: "Historia uruchomień", content: <RunsHistory /> },
        ]}
      />
    </div>
  );
}
