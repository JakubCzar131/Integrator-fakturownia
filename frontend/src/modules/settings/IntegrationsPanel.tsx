/**
 * Zakładka „Integracje”: dane dostępowe Fakturowni i SkyShop utrzymywane
 * w systemie, nie w plikach konfiguracyjnych.
 *
 * Sekret (token / klucz WebAPI) jest wyłącznie wysyłany — API nigdy go nie
 * zwraca, więc w interfejsie widać tylko podpowiedź (••••abcd) i status
 * weryfikacji. Puste pole sekretu przy edycji oznacza „nie zmieniaj”.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatDateTime } from "../../lib/format";
import type {
  ConnectionTestResult,
  EffectiveIntegration,
  IntegrationAccount,
  MessageResponse,
} from "../../lib/types";
import { ConfirmModal, Modal } from "../../components/erp/Modal";
import { useToast } from "../../components/erp/Toast";

const PROVIDERS = [
  {
    value: "FAKTUROWNIA",
    label: "Fakturownia",
    access: "tylko odczyt (GET)",
    secretLabel: "Token API",
    secretHelp: "Fakturownia → Ustawienia → API → kod autoryzacyjny",
  },
  {
    value: "SKYSHOP",
    label: "SkyShop",
    access: "odczyt i zapis (pod przełącznikiem)",
    secretLabel: "Klucz WebAPI",
    secretHelp: "Panel sklepu → Integracje → Web API sklepu",
  },
] as const;

type Provider = (typeof PROVIDERS)[number]["value"];

interface AccountDraft {
  provider: Provider;
  label: string;
  target: string;
  secret: string;
  isActive: boolean;
}

const EMPTY_DRAFT: AccountDraft = {
  provider: "FAKTUROWNIA",
  label: "",
  target: "",
  secret: "",
  isActive: true,
};

function targetOf(account: IntegrationAccount): string {
  const config = account.config ?? {};
  const value = account.provider === "FAKTUROWNIA" ? config.domain : config.base_url;
  return typeof value === "string" ? value : "";
}

function providerMeta(provider: string) {
  return PROVIDERS.find((entry) => entry.value === provider) ?? PROVIDERS[0];
}

function VerificationBadge({ account }: { account: IntegrationAccount }) {
  if (account.verified_status === "OK") {
    return (
      <span className="badge badge--ok" title={`Ostatni udany test: ${formatDateTime(account.verified_at)}`}>
        połączenie OK
      </span>
    );
  }
  if (account.verified_status === "FAILED") {
    return (
      <span className="badge badge--error" title={account.verified_error ?? undefined}>
        błąd połączenia
      </span>
    );
  }
  return <span className="badge badge--neutral">nietestowane</span>;
}

function AccountModal({
  draft, editingId, onChange, onClose, onSaved,
}: {
  draft: AccountDraft;
  editingId: number | null;
  onChange: (draft: AccountDraft) => void;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [saving, setSaving] = useState(false);
  const meta = providerMeta(draft.provider);
  const isNew = editingId === null;

  const save = async () => {
    setSaving(true);
    try {
      const config = draft.provider === "FAKTUROWNIA"
        ? { domain: draft.target.trim() }
        : { base_url: draft.target.trim() };
      if (isNew) {
        await api.post("/settings/integrations", {
          provider: draft.provider,
          label: draft.label.trim(),
          config,
          secret: draft.secret || undefined,
          is_active: draft.isActive,
        });
      } else {
        await api.patch(`/settings/integrations/${editingId}`, {
          label: draft.label.trim(),
          config,
          // Puste pole = zachowaj zapisany sekret.
          secret: draft.secret || undefined,
          is_active: draft.isActive,
        });
      }
      toast.success(isNew ? "Konto integracji dodane" : "Konto integracji zapisane");
      onSaved();
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd zapisu");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={isNew ? "Nowe konto integracji" : "Edycja konta integracji"}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Anuluj</button>
          <button className="btn btn--primary" disabled={saving} onClick={save}>
            {saving ? "Zapisywanie…" : "Zapisz"}
          </button>
        </>
      }
    >
      <div className="form-grid">
        <div className="form-field">
          <label>System</label>
          <select
            value={draft.provider}
            disabled={!isNew}
            onChange={(e) => onChange({ ...draft, provider: e.target.value as Provider })}
          >
            {PROVIDERS.map((entry) => (
              <option key={entry.value} value={entry.value}>{entry.label}</option>
            ))}
          </select>
        </div>
        <div className="form-field">
          <label>Nazwa konta</label>
          <input
            value={draft.label}
            placeholder={draft.provider === "SKYSHOP" ? "np. Sklep główny" : "np. Konto główne"}
            onChange={(e) => onChange({ ...draft, label: e.target.value })}
          />
        </div>
        <div className="form-field form-field--full">
          <label>
            {draft.provider === "FAKTUROWNIA" ? "Domena Fakturowni" : "Adres sklepu"}
          </label>
          <input
            className="mono"
            value={draft.target}
            placeholder={
              draft.provider === "FAKTUROWNIA" ? "mojafirma" : "https://sklep.example.pl"
            }
            onChange={(e) => onChange({ ...draft, target: e.target.value })}
          />
          <span className="text-muted">
            {draft.provider === "FAKTUROWNIA"
              ? "Sama nazwa konta — adres API powstanie jako mojafirma.fakturownia.pl."
              : "Adres sklepu; końcówka /api zostanie dopisana automatycznie."}
          </span>
        </div>
        <div className="form-field form-field--full">
          <label>{meta.secretLabel}</label>
          <input
            type="password"
            autoComplete="new-password"
            className="mono"
            value={draft.secret}
            placeholder={isNew ? "wklej sekret" : "pozostaw puste, aby nie zmieniać"}
            onChange={(e) => onChange({ ...draft, secret: e.target.value })}
          />
          <span className="text-muted">
            {meta.secretHelp}. Sekret jest szyfrowany w bazie i nigdy nie wraca przez API
            ani nie trafia do logów.
          </span>
        </div>
        <div className="form-field form-field--full">
          <label>Aktywne</label>
          <select
            value={draft.isActive ? "1" : "0"}
            onChange={(e) => onChange({ ...draft, isActive: e.target.value === "1" })}
          >
            <option value="1">Tak — używaj tej konfiguracji</option>
            <option value="0">Nie — konto wyłączone</option>
          </select>
        </div>
      </div>
    </Modal>
  );
}

function EffectiveConfiguration({ rows }: { rows: EffectiveIntegration[] }) {
  return (
    <table className="datagrid">
      <thead>
        <tr>
          <th>System</th><th>Źródło konfiguracji</th><th>Konto</th>
          <th>Adres używany teraz</th><th>Dostęp</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.provider}>
            <td>{providerMeta(row.provider).label}</td>
            <td>
              {row.source === "DATABASE" && <span className="badge badge--ok">z systemu</span>}
              {row.source === "ENV" && <span className="badge badge--warn">z pliku .env</span>}
              {row.source === "NONE" && <span className="badge badge--error">brak</span>}
            </td>
            <td>{row.label ?? "—"}</td>
            <td className="mono">{row.target ?? "— nie skonfigurowano —"}</td>
            <td>{String(row.details.access ?? "—")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function IntegrationsPanel() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [accounts, setAccounts] = useState<IntegrationAccount[]>([]);
  const [effective, setEffective] = useState<EffectiveIntegration[]>([]);
  const [draft, setDraft] = useState<AccountDraft | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deactivating, setDeactivating] = useState<IntegrationAccount | null>(null);
  const [testing, setTesting] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([
      api.get<IntegrationAccount[]>("/settings/integrations"),
      api.get<EffectiveIntegration[]>("/settings/integrations/effective"),
    ])
      .then(([accountRows, effectiveRows]) => {
        setAccounts(accountRows);
        setEffective(effectiveRows);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Błąd pobierania"));
  }, []);

  useEffect(load, [load]);

  const testConnection = async (account: IntegrationAccount) => {
    setTesting(account.id);
    try {
      const result = await api.post<ConnectionTestResult>(
        `/settings/integrations/${account.id}/test-connection`,
      );
      if (result.ok) toast.success(result.message);
      else toast.error(result.message);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Test połączenia nie powiódł się");
    } finally {
      setTesting(null);
    }
  };

  const deactivate = async (account: IntegrationAccount) => {
    try {
      const result = await api.delete<MessageResponse>(`/settings/integrations/${account.id}`);
      toast.success(result.message);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Błąd dezaktywacji");
    }
  };

  if (!isAdmin) {
    return (
      <p className="text-muted">
        Dane dostępowe integracji są widoczne wyłącznie dla administratora.
      </p>
    );
  }

  return (
    <div>
      <div className="panel">
        <div className="panel__header">Konfiguracja obowiązująca</div>
        <div className="panel__body" style={{ padding: 0 }}>
          <EffectiveConfiguration rows={effective} />
        </div>
      </div>

      <div className="panel">
        <div className="panel__header">
          Konta integracji
          <span style={{ flex: 1 }} />
          <button
            className="btn btn--small btn--primary"
            onClick={() => { setEditingId(null); setDraft(EMPTY_DRAFT); }}
          >
            + Dodaj konto
          </button>
        </div>
        <div className="panel__body" style={{ padding: 0 }}>
          {error && <p className="text-muted" style={{ padding: 8 }}>{error}</p>}
          <table className="datagrid">
            <thead>
              <tr>
                <th>System</th><th>Nazwa</th><th>Domena / adres</th><th>Sekret</th>
                <th>Weryfikacja</th><th>Stan</th><th></th>
              </tr>
            </thead>
            <tbody>
              {accounts.length === 0 && (
                <tr className="empty-row">
                  <td colSpan={7}>
                    Brak kont — system korzysta z konfiguracji z pliku .env (jeśli istnieje).
                  </td>
                </tr>
              )}
              {accounts.map((account) => (
                <tr key={account.id}>
                  <td>{providerMeta(account.provider).label}</td>
                  <td>
                    {account.label}
                    {account.is_effective && (
                      <span className="badge badge--info" style={{ marginLeft: 6 }}>używane</span>
                    )}
                  </td>
                  <td className="mono">{targetOf(account) || "—"}</td>
                  <td className="mono">
                    {account.secret_configured
                      ? (account.secret_hint ?? "skonfigurowany")
                      : <span className="badge badge--error">brak</span>}
                  </td>
                  <td><VerificationBadge account={account} /></td>
                  <td>
                    {account.is_active
                      ? <span className="badge badge--ok">aktywne</span>
                      : <span className="badge badge--neutral">wyłączone</span>}
                  </td>
                  <td style={{ display: "flex", gap: 4 }}>
                    <button
                      className="btn btn--small"
                      disabled={testing === account.id}
                      onClick={() => testConnection(account)}
                    >
                      {testing === account.id ? "Testowanie…" : "Testuj"}
                    </button>
                    <button
                      className="btn btn--small"
                      onClick={() => {
                        setEditingId(account.id);
                        setDraft({
                          provider: account.provider as Provider,
                          label: account.label,
                          target: targetOf(account),
                          secret: "",
                          isActive: account.is_active,
                        });
                      }}
                    >
                      Edytuj
                    </button>
                    {account.is_active && (
                      <button className="btn btn--small" onClick={() => setDeactivating(account)}>
                        Wyłącz
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <div className="panel__header">Jak działa kolejność źródeł</div>
        <div className="panel__body">
          <ol style={{ margin: 0, paddingLeft: 20 }}>
            <li>Aktywne konto zapisane powyżej — konfiguracja obowiązująca.</li>
            <li>
              Zmienne środowiskowe (<span className="mono">.env</span>) — używane tylko wtedy,
              gdy nie ma aktywnego konta, żeby starsze instalacje działały bez zmian.
            </li>
          </ol>
          <p className="text-muted" style={{ marginBottom: 0 }}>
            Klucz główny szyfrowania (<span className="mono">INTEGRATION_MASTER_KEY</span>)
            pozostaje w zmiennych środowiskowych, więc kopia bazy danych nie ujawnia
            sekretów. Klient Fakturowni technicznie blokuje wszystko poza GET; zapis
            wychodzi wyłącznie do SkyShop i wymaga włączenia przełącznika
            <span className="mono"> skyshop_sync_enabled</span>.
          </p>
        </div>
      </div>

      {draft && (
        <AccountModal
          draft={draft}
          editingId={editingId}
          onChange={setDraft}
          onClose={() => setDraft(null)}
          onSaved={load}
        />
      )}
      {deactivating && (
        <ConfirmModal
          title="Wyłączenie konta integracji"
          message={`Konto „${deactivating.label}” zostanie wyłączone (wpis pozostaje w systemie dla zachowania audytu). Kontynuować?`}
          confirmLabel="Wyłącz"
          onConfirm={() => deactivate(deactivating)}
          onClose={() => setDeactivating(null)}
        />
      )}
    </div>
  );
}
