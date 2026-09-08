import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import type { AppSettingsResponse } from "../../lib/types";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { DetailTabs } from "../../components/erp/DetailTabs";
import { useToast } from "../../components/erp/Toast";
import { IntegrationsPanel } from "./IntegrationsPanel";

// Ustawienia edytowalne z interfejsu; pozostałe klucze są tylko do wglądu.
const EDITABLE_KEYS = new Set([
  "stock_sale_invoice_kinds",
  "stock_excluded_invoice_statuses",
  "stock_use_imported_warehouse_actions",
  "validation_max_reasonable_quantity",
  "validation_stock_discrepancy_tolerance",
  "sync_schedule_minutes",
  "sync_rebuild_stock_after_sync",
  "sync_reconcile_after_sync",
  "reconciliation_include_outbound_documents",
  "reconciliation_keep_runs",
  "skyshop_sync_enabled",
  "skyshop_dry_run",
  "skyshop_stock_source",
  "skyshop_stock_warehouse_id",
  "skyshop_auto_stock_push",
  "skyshop_match_by_name",
]);

// Klucze rozstrzygające o wysyłce do sklepu — wyróżnione, bo ich zmiana
// otwiera lub zamyka jedyny kierunek zapisu w całym systemie.
const WRITE_GUARD_KEYS = new Set(["skyshop_sync_enabled", "skyshop_dry_run"]);

const GROUPS: { key: string; label: string; match: (key: string) => boolean }[] = [
  {
    key: "stock",
    label: "Magazyn i walidacja",
    match: (key) => key.startsWith("stock_") || key.startsWith("validation_"),
  },
  {
    key: "sync",
    label: "Synchronizacja i rozliczenie",
    match: (key) => key.startsWith("sync_") || key.startsWith("reconciliation_"),
  },
  {
    key: "skyshop",
    label: "SkyShop",
    match: (key) => key.startsWith("skyshop_"),
  },
];

function SettingsTable({
  rows, editable, onSave,
}: {
  rows: AppSettingsResponse["settings"];
  editable: boolean;
  onSave: (key: string, raw: string) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  useEffect(() => {
    setDrafts(Object.fromEntries(rows.map((row) => [row.key, JSON.stringify(row.value)])));
  }, [rows]);

  return (
    <table className="datagrid">
      <thead>
        <tr><th>Klucz</th><th>Wartość (JSON)</th><th>Opis</th><th></th></tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr className="empty-row"><td colSpan={4}>Brak ustawień w tej grupie</td></tr>
        )}
        {rows.map((setting) => {
          const canEdit = editable && EDITABLE_KEYS.has(setting.key);
          return (
            <tr key={setting.key}>
              <td className="mono">
                {setting.key}
                {WRITE_GUARD_KEYS.has(setting.key) && (
                  <span className="badge badge--warn" style={{ marginLeft: 6 }}>zapis</span>
                )}
              </td>
              <td>
                {canEdit ? (
                  <input
                    className="mono"
                    style={{ width: 260, height: 23, border: "1px solid var(--c-border)", padding: "0 4px" }}
                    value={drafts[setting.key] ?? ""}
                    onChange={(e) => setDrafts({ ...drafts, [setting.key]: e.target.value })}
                  />
                ) : (
                  <span className="mono">{JSON.stringify(setting.value)}</span>
                )}
              </td>
              <td>{setting.description ?? "—"}</td>
              <td>
                {canEdit && (
                  <button
                    className="btn btn--small"
                    onClick={() => onSave(setting.key, drafts[setting.key] ?? "")}
                  >
                    Zapisz
                  </button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function SettingsPage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [data, setData] = useState<AppSettingsResponse | null>(null);

  const load = useCallback(() => {
    api.get<AppSettingsResponse>("/settings").then(setData).catch(() => undefined);
  }, []);

  useEffect(load, [load]);

  const save = async (key: string, raw: string) => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      toast.error("Nieprawidłowa wartość (użyj formatu JSON, np. [\"vat\"], true, 100)");
      return;
    }
    try {
      await api.patch("/settings", { values: { [key]: parsed } });
      toast.success(`Ustawienie ${key} zapisane`);
      load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd zapisu");
    }
  };

  if (!data) return <p className="text-muted">Ładowanie…</p>;

  const grouped = GROUPS.map((group) => ({
    ...group,
    rows: data.settings.filter((setting) => group.match(setting.key)),
  }));
  const other = data.settings.filter(
    (setting) => !GROUPS.some((group) => group.match(setting.key)),
  );

  return (
    <div>
      <ActionToolbar title="Ustawienia" />

      <DetailTabs
        tabs={[
          { key: "integrations", label: "Integracje", content: <IntegrationsPanel /> },
          ...grouped.map((group) => ({
            key: group.key,
            label: group.label,
            content: (
              <SettingsTable rows={group.rows} editable={isAdmin} onSave={save} />
            ),
          })),
          {
            key: "other",
            label: "Pozostałe",
            content: <SettingsTable rows={other} editable={isAdmin} onSave={save} />,
          },
        ]}
      />
    </div>
  );
}
