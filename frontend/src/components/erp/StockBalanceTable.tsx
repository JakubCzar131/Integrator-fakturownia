/**
 * StockBalanceTable — tabela stanów magazynowych (lokalny vs Fakturownia)
 * z eksportem i filtrami; reużywana w modułach Stany magazynowe i Magazyny.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, buildQuery } from "../../lib/api";
import { formatDateTime, formatQty } from "../../lib/format";
import type { StockBalance } from "../../lib/types";
import { usePagedData } from "../../lib/usePagedData";
import { DataGrid, useGridState, type ColumnDef } from "../datagrid/DataGrid";
import { FilterBar, FilterField } from "./FilterBar";
import { useToast } from "./Toast";

export function StockBalanceTable({ warehouseId }: { warehouseId?: number }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [gridState, setGridState] = useGridState();
  const [search, setSearch] = useState("");
  const [onlyNegative, setOnlyNegative] = useState(false);
  const [onlyDiscrepancies, setOnlyDiscrepancies] = useState(false);

  const filters = {
    search: search || undefined,
    warehouse_id: warehouseId,
    only_negative: onlyNegative || undefined,
    only_discrepancies: onlyDiscrepancies || undefined,
  };
  const { data, loading } = usePagedData<StockBalance>("/stock/balances", gridState, filters);

  const exportReport = async (format: "csv" | "xlsx") => {
    try {
      await api.download(
        `/reports/stock-discrepancies${buildQuery({ format })}`,
        `stany_magazynowe.${format}`,
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd eksportu");
    }
  };

  const columns: ColumnDef<StockBalance>[] = [
    { key: "product_name", header: "Produkt", sortable: true, render: (r) => r.product_name },
    { key: "product_code", header: "Kod", render: (r) => r.product_code ?? "—" },
    { key: "warehouse_name", header: "Magazyn", sortable: true, render: (r) => r.warehouse_name },
    {
      key: "quantity", header: "Stan lokalny", sortable: true, numeric: true,
      render: (r) => formatQty(r.quantity),
      cellClass: (r) => (parseFloat(r.quantity) < 0 ? "negative" : undefined),
    },
    {
      key: "fakturownia_quantity", header: "Stan Fakturownia", numeric: true,
      render: (r) => formatQty(r.fakturownia_quantity),
    },
    {
      key: "difference", header: "Różnica", numeric: true,
      render: (r) => formatQty(r.difference),
      cellClass: (r) =>
        r.difference && parseFloat(r.difference) !== 0 ? "negative" : undefined,
    },
    { key: "product_unit", header: "Jm.", render: (r) => r.product_unit ?? "—" },
    {
      key: "last_movement_at", header: "Ostatni ruch", sortable: true, defaultHidden: false,
      render: (r) => formatDateTime(r.last_movement_at),
    },
    {
      key: "last_sale_at", header: "Ostatnia sprzedaż", sortable: true, defaultHidden: true,
      render: (r) => formatDateTime(r.last_sale_at),
    },
  ];

  return (
    <div>
      <FilterBar>
        <FilterField label="Szukaj produktu">
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="nazwa / kod" />
        </FilterField>
        <FilterField label="Tylko ujemne">
          <input type="checkbox" checked={onlyNegative} onChange={(e) => setOnlyNegative(e.target.checked)} />
        </FilterField>
        <FilterField label="Tylko różnice">
          <input
            type="checkbox"
            checked={onlyDiscrepancies}
            onChange={(e) => setOnlyDiscrepancies(e.target.checked)}
          />
        </FilterField>
        <span style={{ flex: 1 }} />
        <button className="btn btn--small" onClick={() => exportReport("csv")}>Eksport CSV</button>
        <button className="btn btn--small" onClick={() => exportReport("xlsx")}>Eksport XLSX</button>
      </FilterBar>
      <DataGrid
        tableKey={warehouseId ? `stock-balances-wh` : "stock-balances"}
        columns={columns}
        data={data}
        loading={loading}
        state={gridState}
        onStateChange={setGridState}
        rowKey={(r) => r.id}
        onRowClick={(r) => navigate(`/products/${r.product_id}`)}
      />
    </div>
  );
}
