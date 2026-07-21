import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import type { AppSettingsResponse } from "../../lib/types";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { useToast } from "../../components/erp/Toast";

export function SettingsPage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [data, setData] = useState<AppSettingsResponse | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    api.get<AppSettingsResponse>("/settings").then((response) => {
      setData(response);
      const nextDrafts: Record<string, string> = {};
      for (const setting of response.settings) {
        nextDrafts[setting.key] = JSON.stringify(setting.value);
      }
      setDrafts(nextDrafts);
    }).catch(() => undefined);
  }, []);

  useEffect(load, [load]);

  const save = async (key: string) => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(drafts[key]);
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

  const editableKeys = new Set([
    "stock_sale_invoice_kinds", "stock_excluded_invoice_statuses",
    "stock_use_imported_warehouse_actions", "validation_max_reasonable_quantity",
    "validation_stock_discrepancy_tolerance", "sync_schedule_minutes",
  ]);

  return (
    <div>
      <ActionToolbar title="Ustawienia" />

      <div className="panel">
        <div className="panel__header">Połączenie z Fakturownią (tylko odczyt)</div>
        <div className="panel__body">
          <dl className="props">
            <div><dt>Domena</dt><dd>{data.fakturownia.domain ?? "— nie skonfigurowano —"}</dd></div>
            <div><dt>Adres API</dt><dd className="mono">{data.fakturownia.base_url ?? "—"}</dd></div>
            <div>
              <dt>Token API</dt>
              <dd>
                {data.fakturownia.token_configured
                  ? <span className="badge badge--ok">skonfigurowany (ukryty)</span>
                  : <span className="badge badge--error">brak</span>}
              </dd>
            </div>
          </dl>
          <p className="text-muted" style={{ marginBottom: 0 }}>
            Domenę i token konfiguruje się wyłącznie w pliku <b>.env</b>
            (FAKTUROWNIA_DOMAIN, FAKTUROWNIA_API_TOKEN). Token nigdy nie jest
            zwracany przez API ani zapisywany w logach. Klient API blokuje
            technicznie wszystkie żądania inne niż GET.
          </p>
        </div>
      </div>

      <div className="panel">
        <div className="panel__header">Reguły magazynu i walidacji (zapis lokalny)</div>
        <div className="panel__body" style={{ padding: 0 }}>
          <table className="datagrid">
            <thead>
              <tr><th>Klucz</th><th>Wartość (JSON)</th><th>Opis</th><th></th></tr>
            </thead>
            <tbody>
              {data.settings.map((setting) => (
                <tr key={setting.key}>
                  <td className="mono">{setting.key}</td>
                  <td>
                    {editableKeys.has(setting.key) && isAdmin ? (
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
                    {editableKeys.has(setting.key) && isAdmin && (
                      <button className="btn btn--small" onClick={() => save(setting.key)}>Zapisz</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
