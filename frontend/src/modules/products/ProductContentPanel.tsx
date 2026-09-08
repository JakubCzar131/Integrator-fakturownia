/**
 * Edytor treści produktowej (PIM) — lokalne źródło prawdy dla SkyShop.
 *
 * Zapis dotyczy wyłącznie bazy lokalnej. Wysłanie danych do sklepu wymaga
 * osobnej akcji („Publikuj”), która trafia do kolejki zadań i respektuje
 * przełącznik zapisów oraz tryb próbny.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatDateTime } from "../../lib/format";
import type { MessageResponse, ProductContent } from "../../lib/types";
import { useToast } from "../../components/erp/Toast";

interface ImageRow {
  url: string;
  alt: string;
}

interface AttributeRow {
  name: string;
  value: string;
}

interface Draft {
  short_description: string;
  description_html: string;
  price_gross: string;
  vat_rate: string;
  local_category: string;
  weight: string;
  is_publishable: boolean;
  images: ImageRow[];
  attributes: AttributeRow[];
}

function toDraft(content: ProductContent): Draft {
  return {
    short_description: content.short_description ?? "",
    description_html: content.description_html ?? "",
    price_gross: content.price_gross ?? "",
    vat_rate: content.vat_rate ?? "",
    local_category: content.local_category ?? "",
    weight: content.weight ?? "",
    is_publishable: content.is_publishable,
    images: (content.images ?? []).map((image) => ({
      url: String(image.url ?? ""),
      alt: String(image.alt ?? ""),
    })),
    attributes: Object.entries(content.attributes ?? {}).map(([name, value]) => ({
      name,
      value: String(value ?? ""),
    })),
  };
}

export function ProductContentPanel({ productId }: { productId: number }) {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [content, setContent] = useState<ProductContent | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [pushing, setPushing] = useState(false);

  const load = useCallback(() => {
    api.get<ProductContent>(`/products/${productId}/content`)
      .then((response) => {
        setContent(response);
        setDraft(toDraft(response));
      })
      .catch(() => undefined);
  }, [productId]);

  useEffect(load, [load]);

  if (!content || !draft) return <p className="text-muted">Ładowanie…</p>;

  const patch = (changes: Partial<Draft>) => setDraft({ ...draft, ...changes });

  const save = async () => {
    setSaving(true);
    try {
      const attributes: Record<string, string> = {};
      for (const row of draft.attributes) {
        if (row.name.trim()) attributes[row.name.trim()] = row.value;
      }
      const response = await api.put<ProductContent>(`/products/${productId}/content`, {
        short_description: draft.short_description || null,
        description_html: draft.description_html || null,
        price_gross: draft.price_gross === "" ? null : draft.price_gross,
        vat_rate: draft.vat_rate || null,
        local_category: draft.local_category || null,
        weight: draft.weight === "" ? null : draft.weight,
        is_publishable: draft.is_publishable,
        images: draft.images
          .filter((image) => image.url.trim())
          .map((image, index) => ({ url: image.url.trim(), alt: image.alt, position: index })),
        attributes,
      });
      setContent(response);
      setDraft(toDraft(response));
      toast.success("Treść produktu zapisana lokalnie");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd zapisu treści");
    } finally {
      setSaving(false);
    }
  };

  const publish = async () => {
    setPushing(true);
    try {
      const response = await api.post<MessageResponse>("/skyshop/products/push", {
        product_ids: [productId],
        mode: "auto",
      });
      toast.success(response.message);
      load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd kolejkowania publikacji");
    } finally {
      setPushing(false);
    }
  };

  const blocking = content.publication_problems.length > 0;

  return (
    <div>
      <div className="panel">
        <div className="panel__header">
          Gotowość do publikacji w SkyShop
        </div>
        <div className="panel__body">
          {blocking ? (
            <>
              <p style={{ marginTop: 0 }}>
                Produkt nie zostanie wysłany do sklepu, dopóki poniższe braki nie
                zostaną uzupełnione. Publikacja jest blokowana lokalnie — sklep nie
                jest w ogóle wołany.
              </p>
              <ul style={{ margin: 0 }}>
                {content.publication_problems.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            </>
          ) : (
            <p style={{ margin: 0 }}>
              <span className="badge badge--ok">gotowy</span>{" "}
              Dane wystarczają do utworzenia lub aktualizacji produktu w sklepie.
            </p>
          )}
          <dl className="props" style={{ marginBottom: 0 }}>
            <div>
              <dt>Odcisk treści</dt>
              <dd className="mono">{content.content_hash ?? "—"}</dd>
            </div>
            <div>
              <dt>Zapisano lokalnie</dt>
              <dd>{formatDateTime(content.updated_at)}</dd>
            </div>
          </dl>
          {canWrite && (
            <button
              className="btn btn--primary"
              disabled={pushing || blocking}
              onClick={publish}
              title={blocking ? "Uzupełnij braki wymienione powyżej" : undefined}
            >
              {pushing ? "Kolejkowanie…" : "↑ Publikuj w SkyShop (przez kolejkę)"}
            </button>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel__header">Treść dla sklepu</div>
        <div className="panel__body">
          <div className="form-grid">
            <div className="form-field">
              <label>Cena brutto dla sklepu</label>
              <input
                value={draft.price_gross}
                inputMode="decimal"
                disabled={!canWrite}
                onChange={(e) => patch({ price_gross: e.target.value })}
              />
            </div>
            <div className="form-field">
              <label>Stawka VAT</label>
              <input
                value={draft.vat_rate}
                placeholder="np. 23"
                disabled={!canWrite}
                onChange={(e) => patch({ vat_rate: e.target.value })}
              />
            </div>
            <div className="form-field">
              <label>Kategoria lokalna</label>
              <input
                value={draft.local_category}
                placeholder="mapowana na kategorię sklepu"
                disabled={!canWrite}
                onChange={(e) => patch({ local_category: e.target.value })}
              />
            </div>
            <div className="form-field">
              <label>Waga (kg)</label>
              <input
                value={draft.weight}
                inputMode="decimal"
                disabled={!canWrite}
                onChange={(e) => patch({ weight: e.target.value })}
              />
            </div>
            <div className="form-field">
              <label>Publikowalny</label>
              <select
                value={draft.is_publishable ? "1" : "0"}
                disabled={!canWrite}
                onChange={(e) => patch({ is_publishable: e.target.value === "1" })}
              >
                <option value="1">Tak — może trafić do sklepu</option>
                <option value="0">Nie — pomijaj przy publikacji</option>
              </select>
            </div>
            <div className="form-field form-field--full">
              <label>Opis skrócony</label>
              <textarea
                rows={2}
                value={draft.short_description}
                disabled={!canWrite}
                onChange={(e) => patch({ short_description: e.target.value })}
              />
            </div>
            <div className="form-field form-field--full">
              <label>Opis pełny (HTML)</label>
              <textarea
                rows={8}
                className="mono"
                value={draft.description_html}
                disabled={!canWrite}
                onChange={(e) => patch({ description_html: e.target.value })}
              />
            </div>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel__header">Zdjęcia ({draft.images.length})</div>
        <div className="panel__body" style={{ padding: 0 }}>
          <table className="datagrid">
            <thead>
              <tr><th style={{ width: "60%" }}>URL</th><th>Opis alternatywny</th><th /></tr>
            </thead>
            <tbody>
              {draft.images.length === 0 && (
                <tr className="empty-row"><td colSpan={3}>Brak zdjęć</td></tr>
              )}
              {draft.images.map((image, index) => (
                <tr key={index}>
                  <td>
                    <input
                      style={{ width: "100%" }}
                      value={image.url}
                      disabled={!canWrite}
                      onChange={(e) => {
                        const images = [...draft.images];
                        images[index] = { ...image, url: e.target.value };
                        patch({ images });
                      }}
                    />
                  </td>
                  <td>
                    <input
                      style={{ width: "100%" }}
                      value={image.alt}
                      disabled={!canWrite}
                      onChange={(e) => {
                        const images = [...draft.images];
                        images[index] = { ...image, alt: e.target.value };
                        patch({ images });
                      }}
                    />
                  </td>
                  <td>
                    {canWrite && (
                      <button
                        className="btn btn--small"
                        onClick={() => patch({
                          images: draft.images.filter((_, i) => i !== index),
                        })}
                      >
                        usuń
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canWrite && (
          <div className="panel__body">
            <button
              className="btn btn--small"
              onClick={() => patch({ images: [...draft.images, { url: "", alt: "" }] })}
            >
              + Dodaj zdjęcie
            </button>
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel__header">Parametry produktu ({draft.attributes.length})</div>
        <div className="panel__body" style={{ padding: 0 }}>
          <table className="datagrid">
            <thead><tr><th>Parametr</th><th>Wartość</th><th /></tr></thead>
            <tbody>
              {draft.attributes.length === 0 && (
                <tr className="empty-row"><td colSpan={3}>Brak parametrów</td></tr>
              )}
              {draft.attributes.map((attribute, index) => (
                <tr key={index}>
                  <td>
                    <input
                      style={{ width: "100%" }}
                      value={attribute.name}
                      disabled={!canWrite}
                      onChange={(e) => {
                        const attributes = [...draft.attributes];
                        attributes[index] = { ...attribute, name: e.target.value };
                        patch({ attributes });
                      }}
                    />
                  </td>
                  <td>
                    <input
                      style={{ width: "100%" }}
                      value={attribute.value}
                      disabled={!canWrite}
                      onChange={(e) => {
                        const attributes = [...draft.attributes];
                        attributes[index] = { ...attribute, value: e.target.value };
                        patch({ attributes });
                      }}
                    />
                  </td>
                  <td>
                    {canWrite && (
                      <button
                        className="btn btn--small"
                        onClick={() => patch({
                          attributes: draft.attributes.filter((_, i) => i !== index),
                        })}
                      >
                        usuń
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canWrite && (
          <div className="panel__body" style={{ display: "flex", gap: 6 }}>
            <button
              className="btn btn--small"
              onClick={() => patch({ attributes: [...draft.attributes, { name: "", value: "" }] })}
            >
              + Dodaj parametr
            </button>
            <span style={{ flex: 1 }} />
            <button className="btn" onClick={() => setDraft(toDraft(content))}>
              Przywróć zapisane
            </button>
            <button className="btn btn--primary" disabled={saving} onClick={save}>
              {saving ? "Zapisywanie…" : "Zapisz treść lokalnie"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
