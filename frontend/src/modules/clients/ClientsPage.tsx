import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { FakturowniaClient } from "../../lib/types";
import { usePagedData } from "../../lib/usePagedData";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { FilterBar, FilterField } from "../../components/erp/FilterBar";
import { DataGrid, useGridState, type ColumnDef } from "../../components/datagrid/DataGrid";

export function ClientsPage() {
  const navigate = useNavigate();
  const [gridState, setGridState] = useGridState();
  const [search, setSearch] = useState("");
  const { data, loading } = usePagedData<FakturowniaClient>("/clients", gridState, {
    search: search || undefined,
  });

  const columns: ColumnDef<FakturowniaClient>[] = [
    { key: "name", header: "Nazwa", sortable: true, render: (r) => <b>{r.name}</b> },
    { key: "tax_no", header: "NIP", sortable: true, render: (r) => r.tax_no ?? "—" },
    { key: "email", header: "E-mail", render: (r) => r.email ?? "—" },
    { key: "phone", header: "Telefon", defaultHidden: true, render: (r) => r.phone ?? "—" },
    { key: "street", header: "Ulica", defaultHidden: true, render: (r) => r.street ?? "—" },
    { key: "city", header: "Miasto", sortable: true, render: (r) => r.city ?? "—" },
    { key: "post_code", header: "Kod pocztowy", defaultHidden: true, render: (r) => r.post_code ?? "—" },
    { key: "country", header: "Kraj", defaultHidden: true, render: (r) => r.country ?? "—" },
    { key: "fakturownia_id", header: "ID Fakturownia", defaultHidden: true, render: (r) => r.fakturownia_id },
  ];

  return (
    <div>
      <ActionToolbar title="Klienci (z Fakturowni — tylko odczyt)" />
      <FilterBar>
        <FilterField label="Szukaj (nazwa / NIP / e-mail)">
          <input value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 240 }} />
        </FilterField>
      </FilterBar>
      <DataGrid
        tableKey="clients"
        columns={columns}
        data={data}
        loading={loading}
        state={gridState}
        onStateChange={setGridState}
        rowKey={(r) => r.id}
        onRowClick={(r) => navigate(`/invoices?search=${encodeURIComponent(r.name ?? "")}`)}
      />
    </div>
  );
}
