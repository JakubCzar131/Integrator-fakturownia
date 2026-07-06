import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { FilterBar, FilterField } from "../../components/erp/FilterBar";
import { StatusBadge } from "../../components/erp/StatusBadge";
import { DataGrid, useGridState, type ColumnDef } from "../../components/datagrid/DataGrid";
import { formatDate, formatMoney, formatQty } from "../../lib/format";
import type { InvoicePosition } from "../../lib/types";
import { usePagedData } from "../../lib/usePagedData";

export function InvoicePositionsPage() {
  const [searchParams] = useSearchParams();
  const [gridState, setGridState] = useGridState();
  const [search, setSearch] = useState("");
  const [mappingStatus, setMappingStatus] = useState(searchParams.get("mapping_status") ?? "");

  const { data, loading } = usePagedData<InvoicePosition>("/invoice-positions", gridState, {
    search: search || undefined,
    mapping_status: mappingStatus || undefined,
  });

  const columns: ColumnDef<InvoicePosition>[] = [
    {
      key: "invoice_number", header: "Faktura", sortable: true,
      render: (r) => <Link to={`/invoices/${r.invoice_id}`}>{r.invoice_number}</Link>,
    },
    {
      key: "invoice_issue_date", header: "Data", sortable: true,
      render: (r) => formatDate(r.invoice_issue_date),
    },
    { key: "buyer_name", header: "Nabywca", defaultHidden: true, render: (r) => r.buyer_name ?? "—" },
    { key: "name", header: "Nazwa pozycji", sortable: true, render: (r) => r.name },
    { key: "code", header: "Kod", render: (r) => r.code ?? "—" },
    { key: "quantity", header: "Ilość", sortable: true, numeric: true, render: (r) => formatQty(r.quantity) },
    { key: "quantity_unit", header: "Jm.", render: (r) => r.quantity_unit ?? "—" },
    { key: "price_net", header: "Cena netto", sortable: true, numeric: true, render: (r) => formatMoney(r.price_net) },
    { key: "total_price_net", header: "Wartość netto", sortable: true, numeric: true, render: (r) => formatMoney(r.total_price_net) },
    { key: "tax", header: "VAT", defaultHidden: false, render: (r) => r.tax ?? "—" },
    {
      key: "mapping_status", header: "Mapowanie", sortable: true,
      render: (r) => r.mapped_product_id
        ? <StatusBadge value={r.mapping_status ?? undefined} />
        : <span className="badge badge--warn">Brak</span>,
    },
    {
      key: "open_issue_count", header: "Walidacja", sortable: true, numeric: true,
      render: (r) => (r.open_issue_count ?? 0) > 0
        ? <span className="badge badge--error">{r.open_issue_count}</span>
        : <span className="badge badge--ok">OK</span>,
    },
  ];

  return (
    <div>
      <ActionToolbar title="Pozycje faktur — wszystkie" />
      <FilterBar>
        <FilterField label="Szukaj (produkt / pozycja / faktura)">
          <input value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 240 }} />
        </FilterField>
        <FilterField label="Status mapowania">
          <select value={mappingStatus} onChange={(e) => setMappingStatus(e.target.value)}>
            <option value="">— wszystkie —</option>
            <option value="CONFIRMED">Zatwierdzone</option>
            <option value="PROPOSED">Propozycja</option>
            <option value="REJECTED">Konflikt/odrzucone</option>
            <option value="UNMAPPED">Bez mapowania</option>
          </select>
        </FilterField>
      </FilterBar>
      <DataGrid
        tableKey="invoice-positions"
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
