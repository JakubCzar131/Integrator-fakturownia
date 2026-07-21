import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { FilterBar, FilterField } from "../../components/erp/FilterBar";
import { DataGrid, useGridState, type ColumnDef } from "../../components/datagrid/DataGrid";
import { PRODUCT_KIND_LABELS, formatQty } from "../../lib/format";
import type { Product } from "../../lib/types";
import { usePagedData } from "../../lib/usePagedData";

export function ProductsPage() {
  const navigate = useNavigate();
  const [gridState, setGridState] = useGridState();
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [negativeOnly, setNegativeOnly] = useState(false);

  const { data, loading } = usePagedData<Product>("/products", gridState, {
    search: search || undefined,
    kind: kind || undefined,
    negative_stock: negativeOnly || undefined,
  });

  const columns: ColumnDef<Product>[] = [
    { key: "name", header: "Nazwa", sortable: true, render: (r) => <b>{r.name}</b> },
    { key: "code", header: "Kod", sortable: true, render: (r) => r.code ?? "—" },
    { key: "ean", header: "EAN", defaultHidden: true, render: (r) => r.ean ?? "—" },
    { key: "sku", header: "SKU", defaultHidden: true, render: (r) => r.sku ?? "—" },
    { key: "unit", header: "Jm.", render: (r) => r.unit ?? "—" },
    {
      key: "kind", header: "Typ", sortable: true,
      render: (r) => PRODUCT_KIND_LABELS[r.kind] ?? r.kind,
    },
    {
      key: "is_stock_controlled", header: "Kontrola mag.",
      render: (r) => r.is_stock_controlled
        ? <span className="badge badge--info">Tak</span>
        : <span className="badge badge--neutral">Nie</span>,
    },
    {
      key: "is_active", header: "Aktywny",
      render: (r) => r.is_active
        ? <span className="badge badge--ok">Tak</span>
        : <span className="badge badge--error">Nie</span>,
    },
    {
      key: "total_local_stock", header: "Stan lokalny", sortable: true, numeric: true,
      render: (r) => formatQty(r.total_local_stock),
      cellClass: (r) =>
        r.total_local_stock && parseFloat(r.total_local_stock) < 0 ? "negative" : undefined,
    },
    {
      key: "fakturownia_quantity", header: "Stan Fakturownia", numeric: true,
      render: (r) => formatQty(r.fakturownia_quantity),
    },
    {
      key: "open_issue_count", header: "Problemy", sortable: true, numeric: true,
      render: (r) => r.open_issue_count > 0
        ? <span className="badge badge--error">{r.open_issue_count}</span>
        : <span className="badge badge--ok">0</span>,
    },
  ];

  return (
    <div>
      <ActionToolbar title="Produkty" />
      <FilterBar>
        <FilterField label="Szukaj">
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="nazwa / kod / EAN / SKU" style={{ width: 220 }} />
        </FilterField>
        <FilterField label="Typ produktu">
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">— wszystkie —</option>
            {Object.entries(PRODUCT_KIND_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label="Tylko stan ujemny">
          <input type="checkbox" checked={negativeOnly} onChange={(e) => setNegativeOnly(e.target.checked)} />
        </FilterField>
      </FilterBar>
      <DataGrid
        tableKey="products"
        columns={columns}
        data={data}
        loading={loading}
        state={gridState}
        onStateChange={setGridState}
        rowKey={(r) => r.id}
        onRowClick={(r) => navigate(`/products/${r.id}`)}
      />
    </div>
  );
}
