import { useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatDateTime, formatDuration } from "../../lib/format";
import type { SyncRun } from "../../lib/types";
import { usePagedData } from "../../lib/usePagedData";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { Modal } from "../../components/erp/Modal";
import { StatusBadge } from "../../components/erp/StatusBadge";
import { useToast } from "../../components/erp/Toast";
import { DataGrid, useGridState, type ColumnDef } from "../../components/datagrid/DataGrid";

export function SyncPage() {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [gridState, setGridState] = useGridState({ perPage: 25 });
  const [details, setDetails] = useState<SyncRun | null>(null);
  const { data, loading, reload } = usePagedData<SyncRun>("/sync/runs", gridState, {});

  const start = async (type: "full" | "incremental") => {
    try {
      const result = await api.post<{ message: string }>(`/sync/${type}`);
      toast.info(result.message);
      setTimeout(reload, 1500);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd synchronizacji");
    }
  };

  const columns: ColumnDef<SyncRun>[] = [
    { key: "id", header: "#", sortable: true, numeric: true, render: (r) => r.id },
    { key: "run_type", header: "Typ", sortable: true, render: (r) => <StatusBadge value={r.run_type} /> },
    { key: "status", header: "Status", sortable: true, render: (r) => <StatusBadge value={r.status} /> },
    { key: "started_at", header: "Start", sortable: true, render: (r) => formatDateTime(r.started_at) },
    { key: "finished_at", header: "Koniec", render: (r) => formatDateTime(r.finished_at) },
    { key: "duration_seconds", header: "Czas", sortable: true, render: (r) => formatDuration(r.duration_seconds) },
    { key: "records_fetched", header: "Pobrane", sortable: true, numeric: true, render: (r) => r.records_fetched },
    { key: "records_created", header: "Nowe", numeric: true, render: (r) => r.records_created },
    { key: "records_updated", header: "Zmienione", numeric: true, render: (r) => r.records_updated },
    { key: "records_unchanged", header: "Bez zmian", numeric: true, defaultHidden: true, render: (r) => r.records_unchanged },
    {
      key: "error_count", header: "Błędy", sortable: true, numeric: true,
      render: (r) => r.error_count > 0
        ? <span className="badge badge--error">{r.error_count}</span>
        : <span className="badge badge--ok">0</span>,
    },
    { key: "message", header: "Komunikat", render: (r) => r.message ?? "—" },
  ];

  return (
    <div>
      <ActionToolbar title="Synchronizacja z Fakturownią (wyłącznie GET)">
        {canWrite && (
          <>
            <button className="btn btn--primary" onClick={() => start("full")}>⟳ Pełna synchronizacja</button>
            <button className="btn" onClick={() => start("incremental")}>⟳ Synchronizacja przyrostowa</button>
          </>
        )}
        <span className="action-toolbar__spacer" />
        <button className="btn" onClick={reload}>Odśwież</button>
      </ActionToolbar>

      <div className="panel">
        <div className="panel__body text-muted">
          Harmonogram automatycznej synchronizacji konfiguruje się w <b>.env</b>
          (SYNC_SCHEDULE_ENABLED, SYNC_INTERVAL_MINUTES). Integracja jest technicznie
          zablokowana do metody GET — system nigdy nie zapisuje niczego w Fakturowni.
        </div>
      </div>

      <DataGrid
        tableKey="sync-runs"
        columns={columns}
        data={data}
        loading={loading}
        state={gridState}
        onStateChange={setGridState}
        rowKey={(r) => r.id}
        onRowClick={(r) => setDetails(r)}
      />

      {details && (
        <Modal title={`Synchronizacja #${details.id} — szczegóły`} onClose={() => setDetails(null)}>
          {details.errors && details.errors.length > 0 && (
            <>
              <b>Błędy API:</b>
              <ul>{details.errors.map((error, index) => <li key={index} className="mono">{error}</li>)}</ul>
            </>
          )}
          <b>Statystyki per zasób:</b>
          <pre className="raw-json">{JSON.stringify(details.stats, null, 2)}</pre>
        </Modal>
      )}
    </div>
  );
}
