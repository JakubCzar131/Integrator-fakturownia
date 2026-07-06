import { useState } from "react";
import { formatDateTime } from "../../lib/format";
import type { AuditLogEntry } from "../../lib/types";
import { usePagedData } from "../../lib/usePagedData";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { FilterBar, FilterField } from "../../components/erp/FilterBar";
import { Modal } from "../../components/erp/Modal";
import { DataGrid, useGridState, type ColumnDef } from "../../components/datagrid/DataGrid";

const ACTIONS = [
  "CREATE", "UPDATE", "DELETE", "LOGIN", "LOGIN_FAILED", "SYNC_STARTED",
  "VALIDATION_STARTED", "VALIDATION_FINISHED", "STOCK_RECALCULATED",
  "EXPORT", "READONLY_VIOLATION_BLOCKED",
];

export function AuditPage() {
  const [gridState, setGridState] = useGridState();
  const [action, setAction] = useState("");
  const [objectType, setObjectType] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [details, setDetails] = useState<AuditLogEntry | null>(null);

  const { data, loading } = usePagedData<AuditLogEntry>("/audit-log", gridState, {
    action: action || undefined,
    object_type: objectType || undefined,
    user_email: userEmail || undefined,
  });

  const columns: ColumnDef<AuditLogEntry>[] = [
    { key: "id", header: "#", sortable: true, numeric: true, render: (r) => r.id },
    { key: "created_at", header: "Data", sortable: true, render: (r) => formatDateTime(r.created_at) },
    { key: "user_email", header: "Użytkownik", sortable: true, render: (r) => r.user_email ?? "system" },
    {
      key: "action", header: "Operacja", sortable: true,
      render: (r) => r.action === "READONLY_VIOLATION_BLOCKED"
        ? <span className="badge badge--error">{r.action}</span>
        : r.action,
    },
    { key: "object_type", header: "Obiekt", sortable: true, render: (r) => r.object_type ?? "—" },
    { key: "object_id", header: "ID obiektu", defaultHidden: true, render: (r) => r.object_id ?? "—" },
    { key: "description", header: "Opis", render: (r) => r.description ?? "—" },
    { key: "ip_address", header: "IP", defaultHidden: false, render: (r) => r.ip_address ?? "—" },
  ];

  return (
    <div>
      <ActionToolbar title="Audyt operacji lokalnych" />
      <FilterBar>
        <FilterField label="Operacja">
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">— wszystkie —</option>
            {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </FilterField>
        <FilterField label="Typ obiektu">
          <input value={objectType} onChange={(e) => setObjectType(e.target.value)} placeholder="np. product_mapping" />
        </FilterField>
        <FilterField label="Użytkownik">
          <input value={userEmail} onChange={(e) => setUserEmail(e.target.value)} />
        </FilterField>
      </FilterBar>
      <DataGrid
        tableKey="audit-log"
        columns={columns}
        data={data}
        loading={loading}
        state={gridState}
        onStateChange={setGridState}
        rowKey={(r) => r.id}
        onRowClick={(r) => setDetails(r)}
      />
      {details && (
        <Modal title={`Wpis audytu #${details.id}`} onClose={() => setDetails(null)}>
          <dl className="props">
            <div><dt>Data</dt><dd>{formatDateTime(details.created_at)}</dd></div>
            <div><dt>Użytkownik</dt><dd>{details.user_email ?? "system"}</dd></div>
            <div><dt>Operacja</dt><dd>{details.action}</dd></div>
            <div><dt>Obiekt</dt><dd>{details.object_type} {details.object_id ? `#${details.object_id}` : ""}</dd></div>
            <div><dt>IP</dt><dd>{details.ip_address ?? "—"}</dd></div>
          </dl>
          <p>{details.description}</p>
          {details.old_value && (
            <>
              <b>Poprzednia wartość:</b>
              <pre className="raw-json">{JSON.stringify(details.old_value, null, 2)}</pre>
            </>
          )}
          {details.new_value && (
            <>
              <b>Nowa wartość:</b>
              <pre className="raw-json">{JSON.stringify(details.new_value, null, 2)}</pre>
            </>
          )}
        </Modal>
      )}
    </div>
  );
}
