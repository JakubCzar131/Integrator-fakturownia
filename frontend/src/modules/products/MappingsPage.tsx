import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatDate } from "../../lib/format";
import type { ProductMapping } from "../../lib/types";
import { usePagedData } from "../../lib/usePagedData";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { FilterBar, FilterField } from "../../components/erp/FilterBar";
import { ProductMappingModal } from "../../components/erp/ProductMappingModal";
import { StatusBadge } from "../../components/erp/StatusBadge";
import { useToast } from "../../components/erp/Toast";
import { DataGrid, useGridState, type ColumnDef } from "../../components/datagrid/DataGrid";

export function MappingsPage() {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [searchParams] = useSearchParams();
  const [gridState, setGridState] = useGridState();
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState(searchParams.get("search") ?? "");
  const [selected, setSelected] = useState<ProductMapping | null>(null);

  const { data, loading, reload } = usePagedData<ProductMapping>("/product-mappings", gridState, {
    status: status || undefined,
    search: search || undefined,
  });

  const reapply = async () => {
    try {
      const result = await api.post<{ message: string }>("/product-mappings/reapply");
      toast.success(result.message);
      reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd");
    }
  };

  const runValidation = async () => {
    try {
      const run = await api.post<{ message: string | null }>("/validation/run");
      toast.success(run.message ?? "Walidacja zakończona");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd walidacji");
    }
  };

  const columns: ColumnDef<ProductMapping>[] = [
    { key: "source_name", header: "Nazwa źródłowa (z faktur)", sortable: true, render: (r) => r.source_name ?? "—" },
    { key: "source_code", header: "Kod źródłowy", render: (r) => r.source_code ?? "—" },
    { key: "source_ean", header: "EAN", defaultHidden: true, render: (r) => r.source_ean ?? "—" },
    { key: "source_unit", header: "Jm.", defaultHidden: true, render: (r) => r.source_unit ?? "—" },
    {
      key: "occurrence_count", header: "Wystąpienia", sortable: true, numeric: true,
      render: (r) => r.occurrence_count,
    },
    {
      key: "product_name", header: "Zmapowany produkt",
      render: (r) => r.product_name ?? <span className="badge badge--warn">brak</span>,
    },
    { key: "match_type", header: "Typ dopasowania", sortable: true, render: (r) => r.match_type },
    { key: "status", header: "Status", sortable: true, render: (r) => <StatusBadge value={r.status} /> },
    { key: "created_at", header: "Utworzono", sortable: true, render: (r) => formatDate(r.created_at) },
    { key: "confirmed_at", header: "Zatwierdzono", defaultHidden: true, render: (r) => formatDate(r.confirmed_at) },
    { key: "notes", header: "Notatki", defaultHidden: true, render: (r) => r.notes ?? "—" },
  ];

  return (
    <div>
      <ActionToolbar title="Mapowania produktów (lokalne)">
        {canWrite && (
          <>
            <button className="btn" onClick={reapply}>⇄ Zastosuj mapowania ponownie</button>
            <button className="btn btn--primary" onClick={runValidation}>✓ Przelicz walidację</button>
          </>
        )}
      </ActionToolbar>
      <FilterBar>
        <FilterField label="Szukaj">
          <input value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 220 }} />
        </FilterField>
        <FilterField label="Status">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">— wszystkie —</option>
            <option value="PROPOSED">Do zatwierdzenia</option>
            <option value="CONFIRMED">Zatwierdzone</option>
            <option value="REJECTED">Odrzucone</option>
          </select>
        </FilterField>
      </FilterBar>
      <DataGrid
        tableKey="product-mappings"
        columns={columns}
        data={data}
        loading={loading}
        state={gridState}
        onStateChange={setGridState}
        rowKey={(r) => r.id}
        onRowClick={canWrite ? (r) => setSelected(r) : undefined}
      />
      {selected && (
        <ProductMappingModal
          mapping={selected}
          onClose={() => setSelected(null)}
          onSaved={reload}
        />
      )}
    </div>
  );
}
