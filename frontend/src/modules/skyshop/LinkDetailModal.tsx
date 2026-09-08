/**
 * Szczegóły powiązania produkt ↔ SkyShop: ręczne wskazanie produktu w sklepie,
 * wyłączenie produktu z synchronizacji i podgląd ostatniej publikacji.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, buildQuery } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatDateTime, formatMoney, formatQty } from "../../lib/format";
import type { MessageResponse, Page, SkyShopLink, SkyShopProduct } from "../../lib/types";
import { Modal } from "../../components/erp/Modal";
import { StatusBadge } from "../../components/erp/StatusBadge";
import { useToast } from "../../components/erp/Toast";

export function LinkDetailModal({
  link,
  onClose,
  onChanged,
}: {
  link: SkyShopLink;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [search, setSearch] = useState(link.product_sku ?? link.product_name ?? "");
  const [candidates, setCandidates] = useState<SkyShopProduct[]>([]);
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!search.trim()) {
      setCandidates([]);
      return;
    }
    let alive = true;
    setSearching(true);
    const timer = setTimeout(() => {
      api.get<Page<SkyShopProduct>>(
        `/skyshop/products${buildQuery({ search: search.trim(), per_page: 20 })}`,
      )
        .then((page) => alive && setCandidates(page.items))
        .catch(() => alive && setCandidates([]))
        .finally(() => alive && setSearching(false));
    }, 300);
    return () => { alive = false; clearTimeout(timer); };
  }, [search]);

  const patchLink = async (body: Record<string, unknown>, message: string) => {
    setBusy(true);
    try {
      await api.patch<SkyShopLink>(`/skyshop/links/${link.product_id}`, body);
      toast.success(message);
      onChanged();
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd zapisu powiązania");
    } finally {
      setBusy(false);
    }
  };

  const queuePush = async (mode: "auto" | "create" | "update") => {
    setBusy(true);
    try {
      const response = await api.post<MessageResponse>("/skyshop/products/push", {
        product_ids: [link.product_id],
        mode,
        force: true,
      });
      toast.success(response.message);
      onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd kolejkowania publikacji");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Powiązanie SkyShop: ${link.product_name ?? link.product_id}`}
      onClose={onClose}
      footer={
        <>
          <Link className="btn" to={`/products/${link.product_id}`}>Karta produktu →</Link>
          <span style={{ flex: 1 }} />
          <button className="btn" onClick={onClose}>Zamknij</button>
        </>
      }
    >
      <dl className="props">
        <div><dt>Status</dt><dd><StatusBadge value={link.status} /></dd></div>
        <div><dt>Typ dopasowania</dt><dd>{link.match_type ?? "—"}</dd></div>
        <div><dt>SKU lokalne</dt><dd className="mono">{link.product_sku ?? "—"}</dd></div>
        <div><dt>EAN lokalny</dt><dd className="mono">{link.product_ean ?? "—"}</dd></div>
        <div><dt>ID w sklepie</dt><dd className="mono">{link.skyshop_id ?? "—"}</dd></div>
        <div><dt>Nazwa w sklepie</dt><dd>{link.shop_name ?? "—"}</dd></div>
        <div><dt>Stan lokalny</dt><dd>{formatQty(link.local_stock)}</dd></div>
        <div><dt>Stan w sklepie (mirror)</dt><dd>{formatQty(link.shop_stock)}</dd></div>
        <div><dt>Ostatnio wysłany stan</dt><dd>{formatQty(link.last_pushed_stock)}</dd></div>
        <div><dt>Ostatnia publikacja</dt><dd>{formatDateTime(link.last_pushed_at)}</dd></div>
        {link.last_error && (
          <div><dt>Ostatni błąd</dt><dd className="mono">{link.last_error}</dd></div>
        )}
      </dl>

      {link.candidate_skyshop_ids && link.candidate_skyshop_ids.length > 1 && (
        <p className="badge badge--warn">
          Dopasowanie niejednoznaczne — {link.candidate_skyshop_ids.length} kandydatów
          w sklepie. Wskaż właściwy produkt poniżej.
        </p>
      )}

      {canWrite && (
        <>
          <div className="panel">
            <div className="panel__header">Wskaż produkt w sklepie ręcznie</div>
            <div className="panel__body">
              <input
                style={{ width: "100%" }}
                placeholder="szukaj w mirrorze sklepu po nazwie, SKU lub EAN"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <table className="datagrid" style={{ marginTop: 8 }}>
                <thead>
                  <tr>
                    <th>Nazwa w sklepie</th><th>SKU</th><th>EAN</th>
                    <th className="num">Cena</th><th className="num">Stan</th><th />
                  </tr>
                </thead>
                <tbody>
                  {searching && (
                    <tr className="empty-row"><td colSpan={6}>Szukanie…</td></tr>
                  )}
                  {!searching && candidates.length === 0 && (
                    <tr className="empty-row">
                      <td colSpan={6}>
                        Brak trafień w mirrorze. Jeśli produktu nie ma w sklepie,
                        użyj „Dodaj do sklepu”.
                      </td>
                    </tr>
                  )}
                  {!searching && candidates.map((candidate) => (
                    <tr key={candidate.skyshop_id}>
                      <td>{candidate.name ?? "—"}</td>
                      <td className="mono">{candidate.sku ?? "—"}</td>
                      <td className="mono">{candidate.ean ?? "—"}</td>
                      <td className="num">{formatMoney(candidate.price_gross)}</td>
                      <td className="num">{formatQty(candidate.quantity)}</td>
                      <td>
                        <button
                          className="btn btn--small"
                          disabled={busy || candidate.skyshop_id === link.skyshop_id}
                          onClick={() => patchLink(
                            { skyshop_id: candidate.skyshop_id },
                            "Produkt powiązany ze sklepem",
                          )}
                        >
                          {candidate.skyshop_id === link.skyshop_id ? "powiązany" : "powiąż"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="panel">
            <div className="panel__header">Działania</div>
            <div className="panel__body" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              <button
                className="btn btn--primary"
                disabled={busy}
                onClick={() => queuePush(link.skyshop_id ? "update" : "create")}
              >
                {link.skyshop_id
                  ? "↑ Zakolejkuj aktualizację w sklepie"
                  : "+ Dodaj do sklepu (kolejka)"}
              </button>
              {link.status !== "EXCLUDED" ? (
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() => patchLink(
                    { status: "EXCLUDED" },
                    "Produkt wyłączony z synchronizacji ze sklepem",
                  )}
                >
                  Wyłącz z synchronizacji
                </button>
              ) : (
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() => patchLink(
                    { status: link.skyshop_id ? "LINKED" : "MISSING" },
                    "Produkt wrócił do synchronizacji",
                  )}
                >
                  Przywróć do synchronizacji
                </button>
              )}
              {link.skyshop_id && (
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() => patchLink({ skyshop_id: "" }, "Powiązanie usunięte")}
                >
                  Usuń powiązanie
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}
