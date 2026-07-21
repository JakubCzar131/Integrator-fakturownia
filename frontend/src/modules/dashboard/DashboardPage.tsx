import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatDateTime, formatDuration, ISSUE_TYPE_LABELS } from "../../lib/format";
import type { Dashboard } from "../../lib/types";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { StatusBadge } from "../../components/erp/StatusBadge";
import { useToast } from "../../components/erp/Toast";

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const { canWrite } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();

  const load = useCallback(() => {
    api.get<Dashboard>("/dashboard").then(setData).catch(() => undefined);
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [load]);

  const runFullSync = async () => {
    try {
      await api.post("/sync/full");
      toast.info("Pełna synchronizacja uruchomiona w tle");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd");
    }
  };

  const runValidation = async () => {
    try {
      const run = await api.post<{ message: string | null }>("/validation/run");
      toast.success(run.message ?? "Walidacja zakończona");
      load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd");
    }
  };

  if (!data) return <p className="text-muted">Ładowanie…</p>;

  const kpis: {
    label: string; value: number; tone?: "error" | "warn" | "ok"; to?: string;
  }[] = [
    { label: "Faktury", value: data.invoice_count, to: "/invoices" },
    { label: "Pozycje faktur", value: data.position_count, to: "/invoice-positions" },
    { label: "Produkty", value: data.product_count, to: "/products" },
    { label: "Klienci", value: data.client_count, to: "/clients" },
    { label: "Magazyny", value: data.warehouse_count, to: "/warehouses" },
    { label: "Błędy walidacji", value: data.error_count, tone: "error", to: "/validation?status=ERROR" },
    { label: "Ostrzeżenia", value: data.warning_count, tone: "warn", to: "/validation?status=WARNING" },
    { label: "Do zmapowania", value: data.needs_mapping_count, tone: "warn", to: "/mappings" },
    { label: "Brak stanu pocz.", value: data.needs_opening_balance_count, tone: "warn", to: "/validation?status=NEEDS_OPENING_BALANCE" },
    { label: "Pozycje bez mapowania", value: data.unmapped_position_count, tone: "warn", to: "/invoice-positions?mapping_status=UNMAPPED" },
    { label: "Stany ujemne", value: data.negative_stock_count, tone: "error", to: "/stock-balances?only_negative=1" },
  ];

  return (
    <div>
      <ActionToolbar title="Dashboard">
        {canWrite && (
          <>
            <button className="btn" onClick={runFullSync}>⟳ Pełna synchronizacja</button>
            <button className="btn btn--primary" onClick={runValidation}>✓ Uruchom walidację</button>
          </>
        )}
        <button className="btn" onClick={() => navigate("/reports")}>▧ Eksportuj raport</button>
        <span className="action-toolbar__spacer" />
        <button className="btn" onClick={load}>Odśwież</button>
      </ActionToolbar>

      <div className="kpi-grid">
        {kpis.map((kpi) => (
          <div
            key={kpi.label}
            className={`kpi ${kpi.tone ? `kpi--${kpi.tone}` : ""} ${kpi.to ? "kpi--clickable" : ""}`}
            onClick={() => kpi.to && navigate(kpi.to)}
          >
            <div className="kpi__label">{kpi.label}</div>
            <div className={`kpi__value ${kpi.tone ? `kpi__value--${kpi.tone}` : ""}`}>
              {kpi.value.toLocaleString("pl-PL")}
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <div className="panel">
          <div className="panel__header">Ostatnia synchronizacja</div>
          <div className="panel__body">
            {data.last_sync ? (
              <dl className="props">
                <div><dt>Status</dt><dd><StatusBadge value={data.last_sync.status} /></dd></div>
                <div><dt>Typ</dt><dd>{data.last_sync.run_type}</dd></div>
                <div><dt>Start</dt><dd>{formatDateTime(data.last_sync.started_at)}</dd></div>
                <div><dt>Czas trwania</dt><dd>{formatDuration(data.last_sync.duration_seconds)}</dd></div>
                <div><dt>Pobrane rekordy</dt><dd>{data.last_sync.records_fetched}</dd></div>
                <div><dt>Błędy</dt><dd>{data.last_sync.error_count}</dd></div>
              </dl>
            ) : (
              <p className="text-muted">
                Brak synchronizacji — uruchom pełną synchronizację, aby pobrać dane z Fakturowni.
              </p>
            )}
            <p style={{ marginBottom: 0 }}><Link to="/sync">Historia synchronizacji →</Link></p>
          </div>
        </div>

        <div className="panel">
          <div className="panel__header">Ostatnia walidacja</div>
          <div className="panel__body">
            {data.last_validation ? (
              <dl className="props">
                <div><dt>Status</dt><dd><StatusBadge value={data.last_validation.status} /></dd></div>
                <div><dt>Start</dt><dd>{formatDateTime(data.last_validation.started_at)}</dd></div>
                <div><dt>Faktury</dt><dd>{data.last_validation.invoices_checked}</dd></div>
                <div><dt>Pozycje</dt><dd>{data.last_validation.positions_checked}</dd></div>
                <div><dt>Nowe problemy</dt><dd>{data.last_validation.issues_created}</dd></div>
                <div><dt>Zamknięte automatycznie</dt><dd>{data.last_validation.issues_auto_resolved}</dd></div>
              </dl>
            ) : (
              <p className="text-muted">Walidacja nie była jeszcze uruchamiana.</p>
            )}
            <p style={{ marginBottom: 0 }}><Link to="/validation">Wszystkie problemy →</Link></p>
          </div>
        </div>

        <div className="panel">
          <div className="panel__header">Faktury wymagające uwagi</div>
          <div className="panel__body" style={{ padding: 0 }}>
            <table className="datagrid">
              <thead>
                <tr><th>Numer</th><th>Data</th><th>Nabywca</th><th className="num">Problemy</th></tr>
              </thead>
              <tbody>
                {data.invoices_needing_attention.length === 0 && (
                  <tr className="empty-row"><td colSpan={4}>Brak faktur z otwartymi problemami</td></tr>
                )}
                {data.invoices_needing_attention.map((invoice) => (
                  <tr
                    key={invoice.id} className="clickable"
                    onClick={() => navigate(`/invoices/${invoice.id}`)}
                  >
                    <td>{invoice.number}</td>
                    <td>{invoice.issue_date ?? "—"}</td>
                    <td>{invoice.buyer_name ?? "—"}</td>
                    <td className="num negative">{invoice.open_issues}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <div className="panel__header">Otwarte problemy wg typu</div>
          <div className="panel__body" style={{ padding: 0 }}>
            <table className="datagrid">
              <thead><tr><th>Typ problemu</th><th className="num">Liczba</th></tr></thead>
              <tbody>
                {data.issue_type_breakdown.length === 0 && (
                  <tr className="empty-row"><td colSpan={2}>Brak otwartych problemów</td></tr>
                )}
                {data.issue_type_breakdown.map((row) => (
                  <tr
                    key={row.issue_type} className="clickable"
                    onClick={() => navigate(`/validation?issue_type=${row.issue_type}`)}
                  >
                    <td>{ISSUE_TYPE_LABELS[row.issue_type] ?? row.issue_type}</td>
                    <td className="num">{row.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
