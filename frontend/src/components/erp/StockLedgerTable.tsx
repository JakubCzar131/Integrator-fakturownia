/**
 * StockLedgerTable — pełny ledger ruchów magazynowych z filtrami.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { MOVEMENT_TYPE_LABELS, formatDateTime, formatQty } from "../../lib/format";
import type { StockLedgerEntry } from "../../lib/types";
import { usePagedData } from "../../lib/usePagedData";
import { DataGrid, useGridState, type ColumnDef } from "../datagrid/DataGrid";
import { FilterBar, FilterField } from "./FilterBar";

export function StockLedgerTable({
  productId, warehouseId, invoiceId,
}: { productId?: number; warehouseId?: number; invoiceId?: number }) {
  const [gridState, setGridState] = useGridState();
  const [movementType, setMovementType] = useState("");

  const { data, loading } = usePagedData<StockLedgerEntry>("/stock/ledger", gridState, {
    product_id: productId,
    warehouse_id: warehouseId,
    invoice_id: invoiceId,
    movement_type: movementType || undefined,
  });

  const columns: ColumnDef<StockLedgerEntry>[] = [
    { key: "sequence", header: "Lp.", sortable: true, numeric: true, render: (r) => r.sequence },
    { key: "occurred_at", header: "Data", sortable: true, render: (r) => formatDateTime(r.occurred_at) },
    {
      key: "movement_type", header: "Typ ruchu", sortable: true,
      render: (r) => MOVEMENT_TYPE_LABELS[r.movement_type] ?? r.movement_type,
    },
    { key: "product_name", header: "Produkt", sortable: true, render: (r) => (
      <Link to={`/products/${r.product_id}`} onClick={(e) => e.stopPropagation()}>{r.product_name}</Link>
    ) },
    { key: "warehouse_name", header: "Magazyn", render: (r) => r.warehouse_name },
    {
      key: "balance_before", header: "Stan przed", numeric: true,
      render: (r) => formatQty(r.balance_before),
    },
    {
      key: "quantity_change", header: "Zmiana", sortable: true, numeric: true,
      render: (r) => formatQty(r.quantity_change),
      cellClass: (r) => (parseFloat(r.quantity_change) < 0 ? "negative" : undefined),
    },
    {
      key: "balance_after", header: "Stan po", sortable: true, numeric: true,
      render: (r) => formatQty(r.balance_after),
      cellClass: (r) => (parseFloat(r.balance_after) < 0 ? "negative" : undefined),
    },
    {
      key: "invoice_number", header: "Dokument", render: (r) =>
        r.source_invoice_id ? (
          <Link to={`/invoices/${r.source_invoice_id}`} onClick={(e) => e.stopPropagation()}>
            {r.invoice_number ?? `#${r.source_invoice_id}`}
          </Link>
        ) : r.source_adjustment_id ? `Korekta #${r.source_adjustment_id}` : "—",
    },
    { key: "description", header: "Opis", defaultHidden: false, render: (r) => r.description ?? "—" },
  ];

  return (
    <div>
      <FilterBar>
        <FilterField label="Typ ruchu">
          <select value={movementType} onChange={(e) => setMovementType(e.target.value)}>
            <option value="">— wszystkie —</option>
            {Object.entries(MOVEMENT_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </FilterField>
      </FilterBar>
      <DataGrid
        tableKey="stock-ledger"
        columns={columns}
        data={data}
        loading={loading}
        state={gridState}
        onStateChange={setGridState}
        rowKey={(r) => r.id}
      />
    </div>
  );
}
