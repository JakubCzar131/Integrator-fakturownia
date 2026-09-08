/**
 * Lokalna kopia (mirror) katalogu SkyShop. Widok czyta wyłącznie bazę —
 * odświeżenie mirroru to jedyna operacja, która woła sklep, i robi to
 * wyłącznie odczytem.
 */
import { useState } from "react";
import { formatDateTime, formatMoney, formatQty } from "../../lib/format";
import type { SkyShopProduct } from "../../lib/types";
import { DataGrid, useGridState, type ColumnDef } from "../../components/datagrid/DataGrid";
import { FilterBar, FilterField } from "../../components/erp/FilterBar";
import { usePagedData } from "../../lib/usePagedData";

export function SkyShopMirrorTab() {
  const [state, setState] = useGridState({ perPage: 50 });
  const [search, setSearch] = useState("");
  const [onlyUnlinked, setOnlyUnlinked] = useState(false);

  const { data, loading } = usePagedData<SkyShopProduct>("/skyshop/products", state, {
    search: search || undefined,
    only_unlinked: onlyUnlinked || undefined,
  });

  const columns: ColumnDef<SkyShopProduct>[] = [
    { key: "name", header: "Nazwa w sklepie", sortable: true, render: (row) => row.name ?? "—" },
    { key: "sku", header: "SKU", sortable: true, render: (row) => row.sku ?? "—" },
    { key: "ean", header: "EAN", render: (row) => row.ean ?? "—" },
    {
      key: "price_gross", header: "Cena brutto", numeric: true, sortable: true,
      render: (row) => formatMoney(row.price_gross),
    },
    {
      key: "quantity", header: "Stan w sklepie", numeric: true, sortable: true,
      render: (row) => formatQty(row.quantity),
    },
    { key: "skyshop_id", header: "ID w sklepie", render: (row) => <span className="mono">{row.skyshop_id}</span> },
    {
      key: "category_skyshop_id", header: "Kategoria (ID)", defaultHidden: true,
      render: (row) => row.category_skyshop_id ?? "—",
    },
    {
      key: "is_active", header: "Aktywny",
      render: (row) => (row.is_active === false ? <span className="badge badge--neutral">nie</span> : "tak"),
    },
    {
      key: "is_deleted_upstream", header: "Usunięty w sklepie", defaultHidden: true,
      render: (row) => (row.is_deleted_upstream ? <span className="badge badge--warn">tak</span> : "—"),
    },
    {
      key: "last_synced_at", header: "Zaczytany", sortable: true,
      render: (row) => formatDateTime(row.last_synced_at),
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
        <FilterField label="Tylko niepowiązane">
          <select
            value={onlyUnlinked ? "1" : "0"}
            onChange={(e) => { setOnlyUnlinked(e.target.value === "1"); setState({ ...state, page: 1 }); }}
          >
            <option value="0">nie</option>
            <option value="1">tak — bez odpowiednika lokalnego</option>
          </select>
        </FilterField>
      </FilterBar>
      <DataGrid
        tableKey="skyshop-mirror"
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
