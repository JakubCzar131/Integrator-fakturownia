/**
 * Powiązania produktów lokalnych z produktami w SkyShop.
 *
 * Zaznaczone wiersze można zbiorczo zakolejkować do publikacji lub do
 * aktualizacji stanu. Wysyłka nigdy nie odbywa się z tego widoku
 * bezpośrednio — trafia do kolejki `sync_jobs`.
 */
import { useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatDateTime, formatQty } from "../../lib/format";
import type { MessageResponse, SkyShopLink } from "../../lib/types";
import { DataGrid, useGridState, type ColumnDef } from "../../components/datagrid/DataGrid";
import { FilterBar, FilterField } from "../../components/erp/FilterBar";
import { StatusBadge } from "../../components/erp/StatusBadge";
import { useToast } from "../../components/erp/Toast";
import { usePagedData } from "../../lib/usePagedData";
import { LinkDetailModal } from "./LinkDetailModal";

const STATUS_OPTIONS = [
  ["", "— wszystkie —"],
  ["LINKED", "Powiązane"],
  ["MISSING", "Brak w sklepie"],
  ["AMBIGUOUS", "Niejednoznaczne"],
  ["PENDING_CREATE", "Do dodania"],
  ["EXCLUDED", "Wyłączone"],
] as const;

export function SkyShopLinksTab({ onChanged }: { onChanged: () => void }) {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [state, setState] = useGridState({ perPage: 50 });
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [onlyOutOfSync, setOnlyOutOfSync] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [open, setOpen] = useState<SkyShopLink | null>(null);
  const [busy, setBusy] = useState(false);

  const { data, loading, reload } = usePagedData<SkyShopLink>("/skyshop/links", state, {
    search: search || undefined,
    status: status || undefined,
    only_out_of_sync: onlyOutOfSync || undefined,
  });

  const refreshAll = () => { reload(); onChanged(); };

  const toggle = (productId: number) => {
    const next = new Set(selected);
    if (next.has(productId)) next.delete(productId);
    else next.add(productId);
    setSelected(next);
  };

  const toggleAll = () => {
    const visible = (data?.items ?? []).map((item) => item.product_id);
    const allSelected = visible.length > 0 && visible.every((id) => selected.has(id));
    setSelected(allSelected ? new Set() : new Set(visible));
  };

  const runBulk = async (
    action: () => Promise<MessageResponse>,
    fallbackError: string,
  ) => {
    setBusy(true);
    try {
      const response = await action();
      toast.success(response.message);
      setSelected(new Set());
      refreshAll();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : fallbackError);
    } finally {
      setBusy(false);
    }
  };

  const selectedIds = Array.from(selected);

  const columns: ColumnDef<SkyShopLink>[] = [
    {
      key: "select",
      header: "",
      render: (row) => (
        <input
          type="checkbox"
          checked={selected.has(row.product_id)}
          onClick={(e) => e.stopPropagation()}
          onChange={() => toggle(row.product_id)}
          aria-label={`Wybierz ${row.product_name ?? row.product_id}`}
        />
      ),
    },
    {
      key: "product_name", header: "Produkt lokalny", sortable: true,
      render: (row) => row.product_name ?? row.product_id,
    },
    { key: "product_sku", header: "SKU", render: (row) => row.product_sku ?? "—" },
    { key: "product_ean", header: "EAN", defaultHidden: true, render: (row) => row.product_ean ?? "—" },
    { key: "status", header: "Status", sortable: true, render: (row) => <StatusBadge value={row.status} /> },
    { key: "match_type", header: "Dopasowanie", defaultHidden: true, render: (row) => row.match_type ?? "—" },
    { key: "shop_name", header: "Nazwa w sklepie", render: (row) => row.shop_name ?? "—" },
    { key: "skyshop_id", header: "ID w sklepie", defaultHidden: true, render: (row) => row.skyshop_id ?? "—" },
    {
      key: "local_stock", header: "Stan lokalny", numeric: true,
      render: (row) => formatQty(row.local_stock),
    },
    {
      key: "shop_stock", header: "Stan w sklepie", numeric: true,
      render: (row) => formatQty(row.shop_stock),
    },
    {
      key: "last_pushed_stock", header: "Wysłany stan", numeric: true, sortable: true,
      cellClass: (row) => (row.stock_out_of_sync ? "negative" : undefined),
      render: (row) => formatQty(row.last_pushed_stock),
    },
    {
      key: "sync", header: "Do wysłania",
      render: (row) => (
        <>
          {row.stock_out_of_sync && <span className="badge badge--warn">stan</span>}
          {row.content_out_of_sync && <span className="badge badge--warn">treść</span>}
          {!row.stock_out_of_sync && !row.content_out_of_sync && (
            <span className="text-muted">—</span>
          )}
        </>
      ),
    },
    {
      key: "last_pushed_at", header: "Ostatnia publikacja", sortable: true,
      render: (row) => formatDateTime(row.last_pushed_at),
    },
    {
      key: "last_error", header: "Ostatni błąd", defaultHidden: true,
      render: (row) => row.last_error ?? "—",
    },
  ];

  return (
    <>
      <FilterBar>
        <FilterField label="Szukaj (nazwa / SKU / EAN)">
          <input
            style={{ width: 220 }}
            value={search}
            onChange={(e) => { setSearch(e.target.value); setState({ ...state, page: 1 }); }}
          />
        </FilterField>
        <FilterField label="Status powiązania">
          <select value={status} onChange={(e) => { setStatus(e.target.value); setState({ ...state, page: 1 }); }}>
            {STATUS_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label="Tylko rozjechane">
          <select
            value={onlyOutOfSync ? "1" : "0"}
            onChange={(e) => { setOnlyOutOfSync(e.target.value === "1"); setState({ ...state, page: 1 }); }}
          >
            <option value="0">nie</option>
            <option value="1">tak — stan lub treść do wysłania</option>
          </select>
        </FilterField>
      </FilterBar>

      {canWrite && (
        <div className="filter-bar">
          <button className="btn btn--small" onClick={toggleAll}>
            Zaznacz / odznacz stronę
          </button>
          <span className="text-muted">Wybrano: {selectedIds.length}</span>
          <span style={{ flex: 1 }} />
          <button
            className="btn btn--small"
            disabled={busy || selectedIds.length === 0}
            onClick={() => runBulk(
              () => api.post<MessageResponse>("/skyshop/stock/sync", {
                product_ids: selectedIds,
                force: true,
              }),
              "Błąd kolejkowania stanów",
            )}
          >
            ↕ Zakolejkuj stany
          </button>
          <button
            className="btn btn--small btn--primary"
            disabled={busy || selectedIds.length === 0}
            onClick={() => runBulk(
              () => api.post<MessageResponse>("/skyshop/products/push", {
                product_ids: selectedIds,
                mode: "auto",
                force: true,
              }),
              "Błąd kolejkowania publikacji",
            )}
          >
            ↑ Zakolejkuj publikację
          </button>
        </div>
      )}

      <DataGrid
        tableKey="skyshop-links"
        columns={columns}
        data={data}
        loading={loading}
        state={state}
        onStateChange={setState}
        onRowClick={(row) => setOpen(row)}
        rowKey={(row) => row.product_id}
      />

      {open && (
        <LinkDetailModal
          link={open}
          onClose={() => setOpen(null)}
          onChanged={refreshAll}
        />
      )}
    </>
  );
}
