/**
 * Moduł SkyShop — integracja sklepu: powiązania produktów, katalog sklepu,
 * mapowanie kategorii i kolejka zadań wychodzących.
 *
 * Zasada: każda zmiana w sklepie przechodzi przez kolejkę `sync_jobs`,
 * którą wykonuje worker z limitem jednego żądania na sekundę. Zapisy są
 * dodatkowo chronione globalnym przełącznikiem i trybem próbnym —
 * oba widoczne w nagłówku tego modułu.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { STOCK_SOURCE_LABELS, formatDateTime } from "../../lib/format";
import type { MessageResponse, SkyShopSummary } from "../../lib/types";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { DetailTabs } from "../../components/erp/DetailTabs";
import { useToast } from "../../components/erp/Toast";
import { SkyShopCategoriesTab } from "./SkyShopCategoriesTab";
import { SkyShopJobsTab } from "./SkyShopJobsTab";
import { SkyShopLinksTab } from "./SkyShopLinksTab";
import { SkyShopMirrorTab } from "./SkyShopMirrorTab";

function SummaryPanel({ summary }: { summary: SkyShopSummary }) {
  const statuses = Object.entries(summary.link_status_counts);
  const jobs = Object.entries(summary.job_status_counts);
  return (
    <div className="panel">
      <div className="panel__header">Stan integracji</div>
      <div className="panel__body">
        <dl className="props">
          <div>
            <dt>Zapisy do sklepu</dt>
            <dd>
              {summary.write_enabled
                ? <span className="badge badge--ok">włączone</span>
                : <span className="badge badge--neutral">wyłączone</span>}
            </dd>
          </div>
          <div>
            <dt>Tryb próbny</dt>
            <dd>
              {summary.dry_run
                ? <span className="badge badge--warn">tak — żądania nie docierają do sklepu</span>
                : <span className="badge badge--ok">nie</span>}
            </dd>
          </div>
          <div>
            <dt>Źródło stanów</dt>
            <dd>{STOCK_SOURCE_LABELS[summary.stock_source] ?? summary.stock_source}</dd>
          </div>
          <div>
            <dt>Produktów w mirrorze</dt>
            <dd>{summary.mirror_product_count}</dd>
          </div>
          <div>
            <dt>Mirror zaczytany</dt>
            <dd>{formatDateTime(summary.mirror_synced_at)}</dd>
          </div>
          <div>
            <dt>Ostatnia publikacja</dt>
            <dd>{formatDateTime(summary.last_push_at)}</dd>
          </div>
        </dl>

        {(!summary.write_enabled || summary.dry_run) && (
          <p style={{ marginBottom: 0 }}>
            Zadania będą się kolejkować, ale sklep nie zostanie zmieniony.
            Przełączniki <span className="mono">skyshop_write_enabled</span> i{" "}
            <span className="mono">skyshop_dry_run</span> zmienisz w{" "}
            <Link to="/settings">Ustawieniach</Link>.
          </p>
        )}

        <div className="kpi-grid" style={{ marginTop: 12 }}>
          {statuses.map(([status, count]) => (
            <div key={status} className="kpi">
              <div className="kpi__label">powiązania: {status}</div>
              <div className="kpi__value">{count}</div>
            </div>
          ))}
          {jobs.map(([status, count]) => (
            <div key={status} className="kpi">
              <div className="kpi__label">kolejka: {status}</div>
              <div className="kpi__value">{count}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function SkyShopPage() {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [summary, setSummary] = useState<SkyShopSummary | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);

  const loadSummary = useCallback(() => {
    api.get<SkyShopSummary>("/skyshop/summary").then(setSummary).catch(() => undefined);
  }, []);

  useEffect(loadSummary, [loadSummary, reloadKey]);

  const onChanged = useCallback(() => setReloadKey((key) => key + 1), []);

  const run = async (
    label: string,
    action: () => Promise<MessageResponse>,
    fallbackError: string,
  ) => {
    setBusy(label);
    try {
      const response = await action();
      toast.success(response.message);
      onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : fallbackError);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <ActionToolbar title="SkyShop — synchronizacja sklepu">
        {summary && (
          <>
            {summary.pending_jobs > 0 && (
              <span className="badge badge--info">{summary.pending_jobs} w kolejce</span>
            )}
            {summary.failed_jobs > 0 && (
              <span className="badge badge--error">{summary.failed_jobs} nieudanych</span>
            )}
            {!summary.write_enabled && (
              <span className="badge badge--neutral">zapisy wyłączone</span>
            )}
            {summary.dry_run && <span className="badge badge--warn">tryb próbny</span>}
          </>
        )}
        <span className="action-toolbar__spacer" />
        {canWrite && (
          <>
            <button
              className="btn"
              disabled={busy !== null}
              onClick={() => run(
                "mirror",
                () => api.post<MessageResponse>("/skyshop/mirror/refresh?background=true"),
                "Błąd odświeżania mirroru",
              )}
              title="Pobiera katalog sklepu do lokalnej kopii (operacja tylko czytająca)"
            >
              {busy === "mirror" ? "Kolejkowanie…" : "⟳ Odśwież katalog sklepu"}
            </button>
            <button
              className="btn"
              disabled={busy !== null}
              onClick={() => run(
                "match",
                () => api.post<MessageResponse>("/skyshop/links/match?only_unlinked=true"),
                "Błąd dopasowania produktów",
              )}
              title="Dopasowuje produkty lokalne do produktów w sklepie po SKU i EAN"
            >
              {busy === "match" ? "Dopasowywanie…" : "⇄ Dopasuj produkty"}
            </button>
            <button
              className="btn"
              disabled={busy !== null}
              onClick={() => run(
                "stock",
                () => api.post<MessageResponse>("/skyshop/stock/sync", { force: false }),
                "Błąd kolejkowania stanów",
              )}
              title="Kolejkuje aktualizację stanów tam, gdzie różnią się od ostatnio wysłanych"
            >
              {busy === "stock" ? "Kolejkowanie…" : "↕ Synchronizuj stany"}
            </button>
            <button
              className="btn btn--primary"
              disabled={busy !== null}
              onClick={() => run(
                "process",
                () => api.post<MessageResponse>("/skyshop/jobs/process?limit=10"),
                "Błąd przetwarzania kolejki",
              )}
              title="Wykonuje jeden przebieg workera od razu"
            >
              {busy === "process" ? "Przetwarzanie…" : "▶ Przetwórz kolejkę"}
            </button>
          </>
        )}
      </ActionToolbar>

      {summary && <SummaryPanel summary={summary} />}

      <DetailTabs
        tabs={[
          {
            key: "links", label: "Powiązania produktów",
            content: <SkyShopLinksTab key={reloadKey} onChanged={onChanged} />,
          },
          {
            key: "mirror", label: "Katalog sklepu",
            content: <SkyShopMirrorTab key={reloadKey} />,
          },
          {
            key: "categories", label: "Kategorie",
            content: <SkyShopCategoriesTab key={reloadKey} onChanged={onChanged} />,
          },
          {
            key: "jobs", label: "Kolejka zadań",
            content: <SkyShopJobsTab key={reloadKey} onChanged={onChanged} />,
          },
        ]}
      />
    </div>
  );
}
