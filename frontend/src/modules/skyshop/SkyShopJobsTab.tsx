/**
 * Kolejka wychodząca (`sync_jobs`) — jedyna droga zapisów do SkyShop.
 *
 * Widok pokazuje stan każdego zadania, liczbę prób i błąd ostatniej próby.
 * Zadania nieudane można zwrócić do kolejki albo anulować.
 */
import { useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { JOB_TYPE_LABELS, formatDateTime } from "../../lib/format";
import type { MessageResponse, SyncJob } from "../../lib/types";
import { DataGrid, useGridState, type ColumnDef } from "../../components/datagrid/DataGrid";
import { FilterBar, FilterField } from "../../components/erp/FilterBar";
import { Modal } from "../../components/erp/Modal";
import { StatusBadge } from "../../components/erp/StatusBadge";
import { useToast } from "../../components/erp/Toast";
import { usePagedData } from "../../lib/usePagedData";

const STATUS_OPTIONS = [
  ["", "— wszystkie —"],
  ["PENDING", "Oczekujące"],
  ["RUNNING", "W toku"],
  ["SUCCESS", "Zakończone"],
  ["FAILED", "Nieudane"],
  ["SKIPPED", "Pominięte"],
  ["CANCELLED", "Anulowane"],
] as const;

export function SkyShopJobsTab({ onChanged }: { onChanged: () => void }) {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [state, setState] = useGridState({ perPage: 50 });
  const [status, setStatus] = useState("");
  const [jobType, setJobType] = useState("");
  const [open, setOpen] = useState<SyncJob | null>(null);

  const { data, loading, reload } = usePagedData<SyncJob>("/skyshop/jobs", state, {
    status: status || undefined,
    job_type: jobType || undefined,
  });

  const act = async (job: SyncJob, action: "retry" | "cancel") => {
    try {
      const response = await api.post<MessageResponse>(`/skyshop/jobs/${job.id}/${action}`);
      toast.success(response.message);
      setOpen(null);
      reload();
      onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd operacji na zadaniu");
    }
  };

  const columns: ColumnDef<SyncJob>[] = [
    { key: "id", header: "#", sortable: true, numeric: true, render: (row) => row.id },
    {
      key: "job_type", header: "Rodzaj", sortable: true,
      render: (row) => JOB_TYPE_LABELS[row.job_type] ?? row.job_type,
    },
    {
      key: "product_name", header: "Produkt",
      render: (row) => row.product_name ?? <span className="text-muted">—</span>,
    },
    { key: "status", header: "Status", sortable: true, render: (row) => <StatusBadge value={row.status} /> },
    {
      key: "attempts", header: "Próby", numeric: true,
      cellClass: (row) => (row.attempts >= row.max_attempts ? "negative" : undefined),
      render: (row) => `${row.attempts} / ${row.max_attempts}`,
    },
    { key: "priority", header: "Priorytet", numeric: true, sortable: true, defaultHidden: true, render: (row) => row.priority },
    {
      key: "next_attempt_at", header: "Następna próba", sortable: true,
      render: (row) => formatDateTime(row.next_attempt_at),
    },
    { key: "created_at", header: "Dodane", sortable: true, render: (row) => formatDateTime(row.created_at) },
    { key: "finished_at", header: "Zakończone", defaultHidden: true, render: (row) => formatDateTime(row.finished_at) },
    {
      key: "last_error", header: "Ostatni błąd",
      render: (row) => (row.last_error ? <span className="mono">{row.last_error}</span> : "—"),
    },
    {
      key: "dedupe_key", header: "Klucz deduplikacji", defaultHidden: true,
      render: (row) => row.dedupe_key ?? "—",
    },
  ];

  return (
    <>
      <FilterBar>
        <FilterField label="Status">
          <select value={status} onChange={(e) => { setStatus(e.target.value); setState({ ...state, page: 1 }); }}>
            {STATUS_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label="Rodzaj zadania">
          <select value={jobType} onChange={(e) => { setJobType(e.target.value); setState({ ...state, page: 1 }); }}>
            <option value="">— wszystkie —</option>
            {Object.entries(JOB_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </FilterField>
      </FilterBar>
      <DataGrid
        tableKey="skyshop-jobs"
        columns={columns}
        data={data}
        loading={loading}
        state={state}
        onStateChange={setState}
        onRowClick={(row) => setOpen(row)}
        rowKey={(row) => row.id}
      />

      {open && (
        <Modal
          title={`Zadanie #${open.id}: ${JOB_TYPE_LABELS[open.job_type] ?? open.job_type}`}
          onClose={() => setOpen(null)}
          footer={
            <>
              {canWrite && open.status !== "SUCCESS" && open.status !== "RUNNING" && (
                <>
                  <button className="btn btn--primary" onClick={() => act(open, "retry")}>
                    ⟳ Ponów zadanie
                  </button>
                  {open.status !== "CANCELLED" && (
                    <button className="btn btn--danger" onClick={() => act(open, "cancel")}>
                      Anuluj zadanie
                    </button>
                  )}
                </>
              )}
              <span style={{ flex: 1 }} />
              <button className="btn" onClick={() => setOpen(null)}>Zamknij</button>
            </>
          }
        >
          <dl className="props">
            <div><dt>Status</dt><dd><StatusBadge value={open.status} /></dd></div>
            <div><dt>Produkt</dt><dd>{open.product_name ?? "—"}</dd></div>
            <div><dt>Próby</dt><dd>{open.attempts} / {open.max_attempts}</dd></div>
            <div><dt>Priorytet</dt><dd>{open.priority}</dd></div>
            <div><dt>Dodane</dt><dd>{formatDateTime(open.created_at)}</dd></div>
            <div><dt>Start</dt><dd>{formatDateTime(open.started_at)}</dd></div>
            <div><dt>Koniec</dt><dd>{formatDateTime(open.finished_at)}</dd></div>
            <div><dt>Następna próba</dt><dd>{formatDateTime(open.next_attempt_at)}</dd></div>
            <div><dt>Klucz deduplikacji</dt><dd className="mono">{open.dedupe_key ?? "—"}</dd></div>
          </dl>
          {open.last_error && (
            <>
              <div className="panel__header">Ostatni błąd</div>
              <pre className="raw-json">{open.last_error}</pre>
            </>
          )}
          <div className="panel__header">Ładunek zadania</div>
          <pre className="raw-json">{JSON.stringify(open.payload, null, 2)}</pre>
          {open.result && (
            <>
              <div className="panel__header">Wynik</div>
              <pre className="raw-json">{JSON.stringify(open.result, null, 2)}</pre>
            </>
          )}
        </Modal>
      )}
    </>
  );
}
