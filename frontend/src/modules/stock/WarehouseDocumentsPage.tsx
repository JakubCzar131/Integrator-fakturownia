/**
 * Moduł „Dokumenty magazynowe”: PZ/PW i pozostałe dokumenty pobrane
 * z Fakturowni wraz ze znormalizowanymi pozycjami.
 *
 * Dokumenty są wyłącznie pobierane (GET) — system niczego nie zapisuje
 * w Fakturowni. Przebudowa pozycji działa na zapisanych payloadach i nie
 * wymaga kontaktu z API.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatDate, formatMoney, formatQty } from "../../lib/format";
import type {
  MessageResponse,
  WarehouseDocument,
  WarehouseDocumentPosition,
  WarehouseDocumentSummary,
  Warehouse,
} from "../../lib/types";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { DataGrid, useGridState, type ColumnDef } from "../../components/datagrid/DataGrid";
import { DetailTabs } from "../../components/erp/DetailTabs";
import { FilterBar, FilterField } from "../../components/erp/FilterBar";
import { Modal } from "../../components/erp/Modal";
import { StatusBadge } from "../../components/erp/StatusBadge";
import { useToast } from "../../components/erp/Toast";
import { usePagedData } from "../../lib/usePagedData";

const KIND_LABELS: Record<string, string> = {
  PZ: "PZ — przyjęcie zewnętrzne",
  PW: "PW — przyjęcie wewnętrzne",
  WZ: "WZ — wydanie zewnętrzne",
  RW: "RW — rozchód wewnętrzny",
  MM: "MM — przesunięcie",
  ZW: "ZW — zwrot",
  OTHER: "inny",
};

function KindBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-muted">—</span>;
  const tone = value === "PZ" || value === "PW" ? "ok" : "info";
  return (
    <span className={`badge badge--${tone}`} title={KIND_LABELS[value] ?? value}>
      {value}
    </span>
  );
}

function DocumentDetail({ documentId, onClose }: { documentId: number; onClose: () => void }) {
  const [document, setDocument] = useState<WarehouseDocument | null>(null);

  useEffect(() => {
    api.get<WarehouseDocument>(`/warehouse-documents/${documentId}`)
      .then(setDocument)
      .catch(() => undefined);
  }, [documentId]);

  return (
    <Modal
      title={document ? `Dokument ${document.number ?? document.fakturownia_id}` : "Dokument"}
      onClose={onClose}
      footer={<button className="btn" onClick={onClose}>Zamknij</button>}
    >
      {!document ? (
        <p className="text-muted">Ładowanie…</p>
      ) : (
        <>
          <dl className="props">
            <div><dt>Rodzaj</dt><dd><KindBadge value={document.kind} /></dd></div>
            <div><dt>Data wystawienia</dt><dd>{formatDate(document.issue_date)}</dd></div>
            <div><dt>Magazyn</dt><dd>{document.warehouse_name ?? "—"}</dd></div>
            <div><dt>ID Fakturownia</dt><dd className="mono">{document.fakturownia_id}</dd></div>
            <div><dt>Opis</dt><dd>{document.description ?? "—"}</dd></div>
            <div><dt>Pozycji</dt><dd>{document.position_count}</dd></div>
            <div><dt>Suma ilości</dt><dd>{formatQty(document.total_quantity)}</dd></div>
            <div>
              <dt>Bez mapowania</dt>
              <dd>
                {document.unmapped_position_count > 0
                  ? <span className="badge badge--warn">{document.unmapped_position_count}</span>
                  : "—"}
              </dd>
            </div>
          </dl>
          <table className="datagrid">
            <thead>
              <tr>
                <th>Nazwa z dokumentu</th><th>Kod</th><th className="num">Ilość</th>
                <th>Jm.</th><th className="num">Cena zakupu netto</th>
                <th>Produkt lokalny</th><th>Mapowanie</th>
              </tr>
            </thead>
            <tbody>
              {(document.positions ?? []).length === 0 && (
                <tr className="empty-row">
                  <td colSpan={7}>
                    Brak znormalizowanych pozycji — użyj „Przebuduj pozycje”.
                  </td>
                </tr>
              )}
              {document.positions?.map((position) => (
                <tr key={position.id}>
                  <td>{position.name ?? "—"}</td>
                  <td className="mono">{position.code ?? "—"}</td>
                  <td className="num">{formatQty(position.quantity)}</td>
                  <td>{position.quantity_unit ?? "—"}</td>
                  <td className="num">{formatMoney(position.purchase_price_net)}</td>
                  <td>
                    {position.mapped_product_id ? (
                      <Link to={`/products/${position.mapped_product_id}`}>
                        {position.product_name ?? position.mapped_product_id}
                      </Link>
                    ) : (
                      <Link to="/mappings">— zmapuj →</Link>
                    )}
                  </td>
                  <td><StatusBadge value={position.mapping_status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Modal>
  );
}

function DocumentsTab({ onOpen }: { onOpen: (id: number) => void }) {
  const [state, setState] = useGridState({ perPage: 50 });
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [onlyInbound, setOnlyInbound] = useState(true);
  const [warehouseId, setWarehouseId] = useState("");
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);

  useEffect(() => {
    api.get<Warehouse[]>("/warehouses").then(setWarehouses).catch(() => undefined);
  }, []);

  const { data, loading } = usePagedData<WarehouseDocument>("/warehouse-documents", state, {
    search: search || undefined,
    kind: kind || undefined,
    only_inbound: onlyInbound || undefined,
    warehouse_fakturownia_id:
      warehouses.find((warehouse) => String(warehouse.id) === warehouseId)?.fakturownia_id
      ?? undefined,
  });

  const columns: ColumnDef<WarehouseDocument>[] = [
    { key: "number", header: "Numer", sortable: true, render: (row) => row.number ?? "—" },
    { key: "kind", header: "Rodzaj", sortable: true, render: (row) => <KindBadge value={row.kind} /> },
    { key: "issue_date", header: "Data", sortable: true, render: (row) => formatDate(row.issue_date) },
    { key: "warehouse_name", header: "Magazyn", render: (row) => row.warehouse_name ?? "—" },
    { key: "position_count", header: "Pozycji", numeric: true, render: (row) => row.position_count },
    {
      key: "total_quantity", header: "Suma ilości", numeric: true,
      render: (row) => formatQty(row.total_quantity),
    },
    {
      key: "unmapped_position_count", header: "Bez mapowania", numeric: true,
      cellClass: (row) => (row.unmapped_position_count > 0 ? "negative" : undefined),
      render: (row) => (row.unmapped_position_count > 0 ? row.unmapped_position_count : "—"),
    },
    { key: "description", header: "Opis", defaultHidden: true, render: (row) => row.description ?? "—" },
    {
      key: "is_deleted_upstream", header: "Usunięty w źródle", defaultHidden: true,
      render: (row) => (row.is_deleted_upstream ? "tak" : "—"),
    },
  ];

  return (
    <>
      <FilterBar>
        <FilterField label="Szukaj (numer / opis)">
          <input value={search} onChange={(e) => { setSearch(e.target.value); setState({ ...state, page: 1 }); }} />
        </FilterField>
        <FilterField label="Rodzaj">
          <select value={kind} onChange={(e) => { setKind(e.target.value); setState({ ...state, page: 1 }); }}>
            <option value="">wszystkie</option>
            {Object.keys(KIND_LABELS).map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label="Magazyn">
          <select value={warehouseId} onChange={(e) => { setWarehouseId(e.target.value); setState({ ...state, page: 1 }); }}>
            <option value="">wszystkie</option>
            {warehouses.map((warehouse) => (
              <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label="Tylko przyjęcia">
          <select
            value={onlyInbound ? "1" : "0"}
            onChange={(e) => { setOnlyInbound(e.target.value === "1"); setState({ ...state, page: 1 }); }}
          >
            <option value="1">tak — PZ i PW</option>
            <option value="0">nie — wszystkie dokumenty</option>
          </select>
        </FilterField>
      </FilterBar>
      <DataGrid
        tableKey="warehouse-documents"
        columns={columns}
        data={data}
        loading={loading}
        state={state}
        onStateChange={setState}
        onRowClick={(row) => onOpen(row.id)}
        rowKey={(row) => row.id}
      />
    </>
  );
}

function PositionsTab({ initialProductId }: { initialProductId: string | null }) {
  const [state, setState] = useGridState({ perPage: 50 });
  const [search, setSearch] = useState("");
  const [documentKind, setDocumentKind] = useState("");
  const [onlyUnmapped, setOnlyUnmapped] = useState(false);

  const { data, loading } = usePagedData<WarehouseDocumentPosition>(
    "/warehouse-documents/positions",
    state,
    {
      search: search || undefined,
      document_kind: documentKind || undefined,
      only_unmapped: onlyUnmapped || undefined,
      product_id: initialProductId || undefined,
      only_inbound: documentKind ? undefined : true,
    },
  );

  const columns: ColumnDef<WarehouseDocumentPosition>[] = [
    { key: "document_number", header: "Dokument", render: (row) => row.document_number ?? "—" },
    {
      key: "document_kind", header: "Rodzaj", sortable: true,
      render: (row) => <KindBadge value={row.document_kind} />,
    },
    { key: "issue_date", header: "Data", sortable: true, render: (row) => formatDate(row.issue_date) },
    { key: "name", header: "Nazwa z dokumentu", sortable: true, render: (row) => row.name ?? "—" },
    { key: "code", header: "Kod", render: (row) => row.code ?? "—" },
    { key: "quantity", header: "Ilość", numeric: true, sortable: true, render: (row) => formatQty(row.quantity) },
    { key: "quantity_unit", header: "Jm.", render: (row) => row.quantity_unit ?? "—" },
    {
      key: "purchase_price_net", header: "Cena zakupu netto", numeric: true, sortable: true,
      render: (row) => formatMoney(row.purchase_price_net),
    },
    {
      key: "product_name", header: "Produkt lokalny",
      render: (row) => (row.mapped_product_id ? (
        <Link to={`/products/${row.mapped_product_id}`}>
          {row.product_name ?? row.mapped_product_id}
        </Link>
      ) : (
        <Link to="/mappings">— zmapuj →</Link>
      )),
    },
    {
      key: "mapping_status", header: "Mapowanie",
      render: (row) => <StatusBadge value={row.mapping_status} />,
    },
  ];

  return (
    <>
      <FilterBar>
        <FilterField label="Szukaj (nazwa / kod)">
          <input value={search} onChange={(e) => { setSearch(e.target.value); setState({ ...state, page: 1 }); }} />
        </FilterField>
        <FilterField label="Rodzaj dokumentu">
          <select value={documentKind} onChange={(e) => { setDocumentKind(e.target.value); setState({ ...state, page: 1 }); }}>
            <option value="">przyjęcia (PZ, PW)</option>
            {Object.keys(KIND_LABELS).map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label="Tylko bez mapowania">
          <select
            value={onlyUnmapped ? "1" : "0"}
            onChange={(e) => { setOnlyUnmapped(e.target.value === "1"); setState({ ...state, page: 1 }); }}
          >
            <option value="0">nie</option>
            <option value="1">tak</option>
          </select>
        </FilterField>
      </FilterBar>
      <DataGrid
        tableKey="warehouse-document-positions"
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

export function WarehouseDocumentsPage() {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [searchParams] = useSearchParams();
  const [summary, setSummary] = useState<WarehouseDocumentSummary | null>(null);
  const [openDocumentId, setOpenDocumentId] = useState<number | null>(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const loadSummary = useCallback(() => {
    api.get<WarehouseDocumentSummary>("/warehouse-documents/summary")
      .then(setSummary)
      .catch(() => undefined);
  }, []);

  useEffect(loadSummary, [loadSummary, reloadKey]);

  const rebuild = async () => {
    setRebuilding(true);
    try {
      const result = await api.post<MessageResponse>("/warehouse-documents/rebuild-positions");
      toast.success(result.message);
      setReloadKey((key) => key + 1);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd przebudowy pozycji");
    } finally {
      setRebuilding(false);
    }
  };

  const productId = searchParams.get("product_id");

  return (
    <div>
      <ActionToolbar title="Dokumenty magazynowe (PZ / PW)">
        {summary && (
          <>
            <span className="badge badge--info">
              {summary.inbound_position_count} pozycji przyjęć
            </span>
            <span className="badge badge--ok">
              przyjęto {formatQty(summary.inbound_quantity)}
            </span>
            {summary.inbound_unmapped_count > 0 && (
              <span className="badge badge--warn">
                {summary.inbound_unmapped_count} bez mapowania
              </span>
            )}
          </>
        )}
        <span className="action-toolbar__spacer" />
        {canWrite && (
          <button className="btn" disabled={rebuilding} onClick={rebuild}>
            {rebuilding ? "Przebudowa…" : "⟳ Przebuduj pozycje"}
          </button>
        )}
      </ActionToolbar>

      <DetailTabs
        initial={productId ? "positions" : "documents"}
        tabs={[
          {
            key: "documents", label: "Dokumenty",
            content: <DocumentsTab key={reloadKey} onOpen={setOpenDocumentId} />,
          },
          {
            key: "positions", label: "Pozycje przyjęć",
            content: <PositionsTab key={reloadKey} initialProductId={productId} />,
          },
        ]}
      />

      {summary && summary.by_kind.length > 0 && (
        <div className="panel">
          <div className="panel__header">Dokumenty w podziale na rodzaje</div>
          <div className="panel__body" style={{ padding: 0 }}>
            <table className="datagrid">
              <thead><tr><th>Rodzaj</th><th>Opis</th><th className="num">Dokumentów</th></tr></thead>
              <tbody>
                {summary.by_kind.map((entry) => (
                  <tr key={entry.kind}>
                    <td><KindBadge value={entry.kind === "—" ? null : entry.kind} /></td>
                    <td>{KIND_LABELS[entry.kind] ?? "—"}</td>
                    <td className="num">{entry.documents}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {openDocumentId !== null && (
        <DocumentDetail documentId={openDocumentId} onClose={() => setOpenDocumentId(null)} />
      )}
    </div>
  );
}
