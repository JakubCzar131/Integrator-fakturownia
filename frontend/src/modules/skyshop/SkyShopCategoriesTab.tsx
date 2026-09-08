/**
 * Mapowanie kategorii lokalnych na kategorie SkyShop.
 *
 * Bez mapowania produkt nie zostanie opublikowany — sklep wymaga kategorii,
 * a system nie zgaduje jej samodzielnie.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatDateTime } from "../../lib/format";
import type { MessageResponse, SkyShopCategory, SkyShopCategoryMapping } from "../../lib/types";
import { ConfirmModal } from "../../components/erp/Modal";
import { useToast } from "../../components/erp/Toast";

export function SkyShopCategoriesTab({ onChanged }: { onChanged: () => void }) {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [categories, setCategories] = useState<SkyShopCategory[]>([]);
  const [mappings, setMappings] = useState<SkyShopCategoryMapping[]>([]);
  const [localCategory, setLocalCategory] = useState("");
  const [skyshopCategoryId, setSkyshopCategoryId] = useState("");
  const [saving, setSaving] = useState(false);
  const [toDelete, setToDelete] = useState<SkyShopCategoryMapping | null>(null);

  const load = useCallback(() => {
    api.get<SkyShopCategory[]>("/skyshop/categories").then(setCategories).catch(() => undefined);
    api.get<SkyShopCategoryMapping[]>("/skyshop/category-mappings")
      .then(setMappings)
      .catch(() => undefined);
  }, []);

  useEffect(load, [load]);

  const save = async () => {
    if (!localCategory.trim() || !skyshopCategoryId) return;
    setSaving(true);
    try {
      await api.put<SkyShopCategoryMapping>("/skyshop/category-mappings", {
        local_category: localCategory.trim(),
        skyshop_category_id: skyshopCategoryId,
      });
      toast.success("Mapowanie kategorii zapisane");
      setLocalCategory("");
      setSkyshopCategoryId("");
      load();
      onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd zapisu mapowania");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (mapping: SkyShopCategoryMapping) => {
    try {
      const response = await api.delete<MessageResponse>(
        `/skyshop/category-mappings/${mapping.id}`,
      );
      toast.success(response.message);
      load();
      onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd usuwania mapowania");
    }
  };

  return (
    <div>
      {canWrite && (
        <div className="panel">
          <div className="panel__header">Dodaj lub zmień mapowanie</div>
          <div className="panel__body">
            <div className="form-grid">
              <div className="form-field">
                <label>Kategoria lokalna (z danych PIM produktu)</label>
                <input
                  value={localCategory}
                  placeholder="np. Akcesoria"
                  onChange={(e) => setLocalCategory(e.target.value)}
                />
              </div>
              <div className="form-field">
                <label>Kategoria w SkyShop</label>
                <select
                  value={skyshopCategoryId}
                  onChange={(e) => setSkyshopCategoryId(e.target.value)}
                >
                  <option value="">— wybierz —</option>
                  {categories.map((category) => (
                    <option key={category.skyshop_id} value={category.skyshop_id}>
                      {category.path ?? category.name ?? category.skyshop_id}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-field">
                <label>&nbsp;</label>
                <button
                  className="btn btn--primary"
                  disabled={saving || !localCategory.trim() || !skyshopCategoryId}
                  onClick={save}
                >
                  {saving ? "Zapisywanie…" : "Zapisz mapowanie"}
                </button>
              </div>
            </div>
            {categories.length === 0 && (
              <p className="text-muted" style={{ marginBottom: 0 }}>
                Lista kategorii sklepu jest pusta — odśwież mirror, aby ją pobrać.
              </p>
            )}
          </div>
        </div>
      )}

      <div className="panel">
        <div className="panel__header">Mapowania kategorii ({mappings.length})</div>
        <div className="panel__body" style={{ padding: 0 }}>
          <table className="datagrid">
            <thead>
              <tr>
                <th>Kategoria lokalna</th><th>Kategoria SkyShop</th>
                <th>ID w sklepie</th><th>Zmieniono</th><th />
              </tr>
            </thead>
            <tbody>
              {mappings.length === 0 && (
                <tr className="empty-row">
                  <td colSpan={5}>Brak mapowań — produkty z kategoriami nie zostaną opublikowane</td>
                </tr>
              )}
              {mappings.map((mapping) => (
                <tr key={mapping.id}>
                  <td>{mapping.local_category}</td>
                  <td>{mapping.skyshop_category_name ?? <span className="badge badge--warn">brak w mirrorze</span>}</td>
                  <td className="mono">{mapping.skyshop_category_id}</td>
                  <td>{formatDateTime(mapping.updated_at)}</td>
                  <td>
                    {canWrite && (
                      <button className="btn btn--small" onClick={() => setToDelete(mapping)}>
                        usuń
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
        <div className="panel__header">Kategorie w sklepie ({categories.length})</div>
        <div className="panel__body" style={{ padding: 0 }}>
          <table className="datagrid">
            <thead>
              <tr><th>Ścieżka</th><th>Nazwa</th><th>ID</th><th>Zmapowana kategoria lokalna</th></tr>
            </thead>
            <tbody>
              {categories.length === 0 && (
                <tr className="empty-row"><td colSpan={4}>Brak danych — odśwież mirror</td></tr>
              )}
              {categories.map((category) => (
                <tr key={category.skyshop_id}>
                  <td>{category.path ?? "—"}</td>
                  <td>{category.name ?? "—"}</td>
                  <td className="mono">{category.skyshop_id}</td>
                  <td>{category.mapped_local_category ?? <span className="text-muted">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {toDelete && (
        <ConfirmModal
          title="Usunąć mapowanie kategorii?"
          message={`Produkty z kategorią „${toDelete.local_category}” przestaną być publikowane, `
            + "dopóki nie wskażesz nowej kategorii w sklepie."}
          confirmLabel="Usuń mapowanie"
          onConfirm={() => remove(toDelete)}
          onClose={() => setToDelete(null)}
        />
      )}
    </div>
  );
}
