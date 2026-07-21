import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { FilterBar, FilterField } from "../../components/erp/FilterBar";
import { StatusBadge } from "../../components/erp/StatusBadge";
import { DataGrid, useGridState, type ColumnDef } from "../../components/datagrid/DataGrid";
import { formatDate, formatMoney } from "../../lib/format";
import type { Invoice } from "../../lib/types";
import { usePagedData } from "../../lib/usePagedData";

export function InvoicesPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [gridState, setGridState] = useGridState({ perPage: 50 });
  const [number, setNumber] = useState("");
  const [buyer, setBuyer] = useState("");
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [validation, setValidation] = useState(searchParams.get("validation") ?? "");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const { data, loading } = usePagedData<Invoice>("/invoices", gridState, {
    search: searchParams.get("search") ?? undefined,
    number: number || undefined,
    buyer: buyer || undefined,
    kind: kind || undefined,
    invoice_status: status || undefined,
    validation: validation || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  });

  const columns: ColumnDef<Invoice>[] = [
    { key: "number", header: "Numer", sortable: true, render: (r) => <b>{r.number}</b> },
    { key: "kind", header: "Typ", sortable: true, render: (r) => r.kind ?? "—" },
    { key: "issue_date", header: "Data wyst.", sortable: true, render: (r) => formatDate(r.issue_date) },
    { key: "sell_date", header: "Data sprzed.", sortable: true, defaultHidden: true, render: (r) => formatDate(r.sell_date) },
    { key: "buyer_name", header: "Nabywca", sortable: true, render: (r) => r.buyer_name ?? "—" },
    { key: "buyer_tax_no", header: "NIP", defaultHidden: true, render: (r) => r.buyer_tax_no ?? "—" },
    { key: "total_net", header: "Netto", sortable: true, numeric: true, render: (r) => formatMoney(r.total_net) },
    { key: "total_gross", header: "Brutto", sortable: true, numeric: true, render: (r) => formatMoney(r.total_gross) },
    { key: "paid_amount", header: "Zapłacono", numeric: true, defaultHidden: true, render: (r) => formatMoney(r.paid_amount) },
    { key: "currency", header: "Waluta", defaultHidden: true, render: (r) => r.currency ?? "—" },
    {
      key: "invoice_status", header: "Status dok.", sortable: true,
      render: (r) => r.is_cancelled ? <StatusBadge value="cancelled" /> : <StatusBadge value={r.invoice_status ?? undefined} />,
    },
    { key: "position_count", header: "Pozycje", numeric: true, render: (r) => r.position_count },
    {
      key: "open_issue_count", header: "Problemy", sortable: true, numeric: true,
      render: (r) => r.open_issue_count > 0
        ? <span className="badge badge--error">{r.open_issue_count}</span>
        : <span className="badge badge--ok">0</span>,
    },
  ];

  return (
    <div>
      <ActionToolbar title="Faktury (z Fakturowni — tylko odczyt)" />
      <FilterBar>
        <FilterField label="Numer">
          <input value={number} onChange={(e) => setNumber(e.target.value)} />
        </FilterField>
        <FilterField label="Klient">
          <input value={buyer} onChange={(e) => setBuyer(e.target.value)} />
        </FilterField>
        <FilterField label="Typ dokumentu">
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">— wszystkie —</option>
            <option value="vat">Faktura VAT</option>
            <option value="correction">Korekta</option>
            <option value="proforma">Proforma</option>
            <option value="receipt">Paragon</option>
            <option value="advance">Zaliczkowa</option>
            <option value="final">Końcowa</option>
          </select>
        </FilterField>
        <FilterField label="Status dokumentu">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">— wszystkie —</option>
            <option value="issued">Wystawiona</option>
            <option value="sent">Wysłana</option>
            <option value="paid">Opłacona</option>
            <option value="partial">Częściowo opłacona</option>
            <option value="rejected">Odrzucona</option>
          </select>
        </FilterField>
        <FilterField label="Walidacja">
          <select value={validation} onChange={(e) => setValidation(e.target.value)}>
            <option value="">— wszystkie —</option>
            <option value="with_issues">Z problemami</option>
            <option value="clean">Bez problemów</option>
          </select>
        </FilterField>
        <FilterField label="Data od">
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </FilterField>
        <FilterField label="Data do">
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </FilterField>
      </FilterBar>
      <DataGrid
        tableKey="invoices"
        columns={columns}
        data={data}
        loading={loading}
        state={gridState}
        onStateChange={setGridState}
        rowKey={(r) => r.id}
        onRowClick={(r) => navigate(`/invoices/${r.id}`)}
      />
    </div>
  );
}
