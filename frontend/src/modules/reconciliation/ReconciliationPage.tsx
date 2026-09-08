/**
 * Moduł „Rozliczenie dokumentów”: zestawienie stanu z Fakturowni z sumą
 * przyjęć PZ/PW i rozchodem z faktur.
 *
 * Widok czyta wyłącznie ostatni zmaterializowany snapshot, więc filtrowanie,
 * sortowanie i paginacja działają po indeksowanej tabeli — żadne zapytanie do
 * systemów zewnętrznych nie leci przy renderowaniu.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatDateTime, formatDuration, formatQty } from "../../lib/format";
import type {
  MessageResponse,
  Page,
  ReconciliationLine,
  ReconciliationRun,
  Warehouse,
} from "../../lib/types";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { DataGrid, useGridState, type ColumnDef } from "../../components/datagrid/DataGrid";
import { DetailTabs } from "../../components/erp/DetailTabs";
import { FilterBar, FilterField } from "../../components/erp/FilterBar";
import { useToast } from "../../components/erp/Toast";
import { usePagedData } from "../../lib/usePagedData";

const STATUS_TONES: Record<string, string> = {
  OK: "ok",
  DISCREPANCY: "error",
  NO_REMOTE_STOCK: "neutral",
};

const STATUS_TEXTS: Record<string, string> = {
  OK: "zgodne",
  DISCREPANCY: "rozbieżność",
  NO_REMOTE_STOCK: "brak stanu w Fakturowni",
};

function ReconciliationStatus({ value }: { value: string }) {
  return (
    <span className={`badge badge--${STATUS_TONES[value] ?? "neutral"}`}>
      {STATUS_TEXTS[value] ?? value}
    </span>
  );
}

function RunsTab({ reloadKey }: { reloadKey: number }) {
  const [runs, setRuns] = useState<ReconciliationRun[]>([]);
  useEffect(() => {
    api.get<Page<ReconciliationRun>>("/reconciliation/runs?per_page=50")
      .then((page) => setRuns(page.items))
      .catch(() => undefined);
  }, [reloadKey]);

  return (
    <table className="datagrid">
      <thead>
        <tr>
          <th>#</th><th>Rozpoczęto</th><th>Czas</th><th>Wywołanie</th>
          <th className="num">Wierszy</th><th className="num">Rozbieżności</th>
          <th className="num">Tolerancja</th>
        </tr>
      </thead>
      <tbody>
        {runs.length === 0 && (
          <tr className="empty-row"><td colSpan={7}>Brak przeliczeń</td></tr>
        )}
        {runs.map((run) => (
          <tr key={run.id}>
            <td>{run.id}</td>
            <td>{formatDateTime(run.started_at)}</td>
            <td>{formatDuration(run.duration_seconds)}</td>
            <td>{run.trigger === "SYNC" ? "po synchronizacji" : "ręcznie"}</td>
            <td className="num">{run.line_count}</td>
            <td className={`num ${run.discrepancy_count > 0 ? "negative" : ""}`}>
              {run.discrepancy_count}
            </td>
            <td className="num">{formatQty(run.tolerance)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function LinesTab() {
  const [state, setState] = useGridState({ perPage: 50 });
  const [search, setSearch] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [status, setStatus] = useState("");
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);

  useEffect(() => {
    api.get<Warehouse[]>("/warehouses").then(setWarehouses).catch(() => undefined);
  }, []);

  const { data, loading } = usePagedData<ReconciliationLine>(
    "/reconciliation",
    state,
    {
      search: search || undefined,
      warehouse_id: warehouseId || undefined,
      status: status || undefined,
    },
  );

  const columns: ColumnDef<ReconciliationLine>[] = [
    {
      key: "product_name", header: "Produkt", sortable: true,
      render: (row) => (
        <Link to={`/products/${row.product_id}`}>{row.product_name ?? row.product_id}</Link>
      ),
    },
    { key: "product_code", header: "Kod", render: (row) => row.product_code ?? "—" },
    {
      key: "warehouse_name", header: "Magazyn", sortable: true,
      render: (row) => row.warehouse_name ?? "—",
    },
    {
      key: "opening_balance", header: "Stan pocz.", numeric: true, defaultHidden: true,
      render: (row) => formatQty(row.opening_balance),
    },
    { key: "inbound_pz", header: "Σ PZ", numeric: true, sortable: true, render: (row) => formatQty(row.inbound_pz) },
    { key: "inbound_pw", header: "Σ PW", numeric: true, sortable: true, render: (row) => formatQty(row.inbound_pw) },
    {
      key: "sold_invoices", header: "Σ sprzedaż", numeric: true, sortable: true,
      render: (row) => formatQty(row.sold_invoices),
    },
    {
      key: "corrections", header: "Σ korekty", numeric: true, sortable: true,
      render: (row) => formatQty(row.corrections),
    },
    {
      key: "outbound_documents", header: "Σ WZ/RW/MM", numeric: true, defaultHidden: true,
      render: (row) => formatQty(row.outbound_documents),
    },
    {
      key: "computed_stock", header: "Stan wyliczony", numeric: true, sortable: true,
      render: (row) => formatQty(row.computed_stock),
    },
    {
      key: "fakturownia_stock", header: "Stan Fakturownia", numeric: true, sortable: true,
      render: (row) => formatQty(row.fakturownia_stock),
    },
    {
      key: "difference", header: "Różnica", numeric: true, sortable: true,
      cellClass: (row) => (row.status === "DISCREPANCY" ? "negative" : undefined),
      render: (row) => formatQty(row.difference),
    },
    {
      key: "local_ledger_stock", header: "Stan wg ledgera", numeric: true, defaultHidden: true,
      render: (row) => formatQty(row.local_ledger_stock),
    },
    {
      key: "status", header: "Status", sortable: true,
      render: (row) => <ReconciliationStatus value={row.status} />,
    },
    {
      key: "documents", header: "Dokumenty",
      render: (row) => (
        <Link to={`/warehouse-documents?product_id=${row.product_id}`}>PZ/PW →</Link>
      ),
    },
  ];

  return (
    <>
      <FilterBar>
        <FilterField label="Szukaj (nazwa / kod)">
          <input value={search} onChange={(e) => { setSearch(e.target.value); setState({ ...state, page: 1 }); }} />
        </FilterField>
        <FilterField label="Magazyn">
          <select value={warehouseId} onChange={(e) => { setWarehouseId(e.target.value); setState({ ...state, page: 1 }); }}>
            <option value="">wszystkie</option>
            {warehouses.map((warehouse) => (
              <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label="Status">
          <select value={status} onChange={(e) => { setStatus(e.target.value); setState({ ...state, page: 1 }); }}>
            <option value="">wszystkie</option>
            <option value="DISCREPANCY">tylko rozbieżności</option>
            <option value="OK">tylko zgodne</option>
            <option value="NO_REMOTE_STOCK">brak stanu w Fakturowni</option>
          </select>
        </FilterField>
      </FilterBar>
      <DataGrid
        tableKey="reconciliation"
        columns={columns}
        data={data}
        loading={loading}
        state={state}
        onStateChange={setState}
        rowKey={(row) => row.id}
      />
    </>
  );
}

export function ReconciliationPage() {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [summary, setSummary] = useState<ReconciliationRun | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const loadSummary = useCallback(() => {
    api.get<{ run: ReconciliationRun | null }>("/reconciliation/summary")
      .then((response) => setSummary(response.run))
      .catch(() => undefined);
  }, []);

  useEffect(loadSummary, [loadSummary, reloadKey]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      const result = await api.post<MessageResponse>("/reconciliation/refresh");
      toast.success(result.message);
      setReloadKey((key) => key + 1);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd przeliczenia");
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div>
      <ActionToolbar title="Rozliczenie dokumentów (PZ/PW vs faktury)">
        {summary ? (
          <>
            <span className="text-muted">
              Snapshot #{summary.id} z {formatDateTime(summary.finished_at)}
            </span>
            <span className={`badge badge--${summary.discrepancy_count > 0 ? "error" : "ok"}`}>
              {summary.discrepancy_count} rozbieżności / {summary.line_count} wierszy
            </span>
          </>
        ) : (
          <span className="text-muted">Brak snapshotu — uruchom przeliczenie</span>
        )}
        <span className="action-toolbar__spacer" />
        {canWrite && (
          <button className="btn btn--primary" disabled={refreshing} onClick={refresh}>
            {refreshing ? "Przeliczanie…" : "⟳ Przelicz rozliczenie"}
          </button>
        )}
      </ActionToolbar>

      <DetailTabs
        tabs={[
          // Nowe przeliczenie tworzy nowy snapshot, więc widok montuje się od nowa.
          { key: "lines", label: "Zestawienie", content: <LinesTab key={reloadKey} /> },
          { key: "runs", label: "Historia przeliczeń", content: <RunsTab reloadKey={reloadKey} /> },
        ]}
      />

      <div className="panel">
        <div className="panel__header">Jak czytać to zestawienie</div>
        <div className="panel__body">
          <p style={{ marginTop: 0 }}>
            <span className="mono">stan wyliczony = stan początkowy + Σ PZ + Σ PW − Σ sprzedaż − Σ korekty</span>
          </p>
          <p className="text-muted" style={{ marginBottom: 0 }}>
            Korekty przychodzą z Fakturowni jako delty (zwrot 2 szt. to −2), więc ich
            odjęcie zwraca towar na stan. Dokumenty WZ/RW/MM są domyślnie tylko
            informacyjne: przy typowej konfiguracji WZ towarzyszy fakturze, a liczenie
            obu rozliczyłoby ten sam towar dwa razy — zmienia to ustawienie
            <span className="mono"> reconciliation_include_outbound_documents</span>.
            Zestawienie jest warstwą raportową niezależną od ledgera; jego celem jest
            wykrycie niespójności między Fakturownią, dokumentami i fakturami.
          </p>
        </div>
      </div>
    </div>
  );
}
