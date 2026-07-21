/**
 * ProductMappingModal — ręczne przypisanie pozycji/sygnatury do produktu.
 * Zapis wyłącznie lokalny (nigdy do Fakturowni).
 */
import { useEffect, useState } from "react";
import { api, buildQuery } from "../../lib/api";
import type { Page, Product, ProductMapping } from "../../lib/types";
import { Modal } from "./Modal";
import { useToast } from "./Toast";

interface Props {
  mapping: ProductMapping;
  onClose: () => void;
  onSaved: () => void;
}

export function ProductMappingModal({ mapping, onClose, onSaved }: Props) {
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [candidates, setCandidates] = useState<Product[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(mapping.product_id);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      api.get<Page<Product>>(`/products${buildQuery({ search: search || undefined, per_page: 20 })}`)
        .then((page) => setCandidates(page.items))
        .catch(() => undefined);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);

  const save = async (status: "CONFIRMED" | "REJECTED") => {
    if (status === "CONFIRMED" && !selectedId) {
      toast.error("Wybierz produkt do zmapowania");
      return;
    }
    setSaving(true);
    try {
      await api.patch(`/product-mappings/${mapping.id}`, {
        product_id: status === "CONFIRMED" ? selectedId : undefined,
        status,
      });
      toast.success(status === "CONFIRMED" ? "Mapowanie zatwierdzone" : "Mapowanie odrzucone");
      onSaved();
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd zapisu mapowania");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`Mapowanie: ${mapping.source_name ?? mapping.source_code ?? "—"}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Anuluj</button>
          <button className="btn btn--danger" disabled={saving} onClick={() => save("REJECTED")}>
            Odrzuć
          </button>
          <button className="btn btn--primary" disabled={saving} onClick={() => save("CONFIRMED")}>
            Zatwierdź mapowanie
          </button>
        </>
      }
    >
      <dl className="props" style={{ marginBottom: 10 }}>
        <div><dt>Nazwa źródłowa</dt><dd>{mapping.source_name ?? "—"}</dd></div>
        <div><dt>Kod źródłowy</dt><dd>{mapping.source_code ?? "—"}</dd></div>
        <div><dt>EAN</dt><dd>{mapping.source_ean ?? "—"}</dd></div>
        <div><dt>Jednostka</dt><dd>{mapping.source_unit ?? "—"}</dd></div>
        <div><dt>Wystąpień na fakturach</dt><dd>{mapping.occurrence_count}</dd></div>
      </dl>
      <div className="form-field" style={{ marginBottom: 8 }}>
        <label>Szukaj produktu lokalnego</label>
        <input
          autoFocus
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="nazwa, kod, EAN…"
        />
      </div>
      <div style={{ maxHeight: 260, overflow: "auto", border: "1px solid var(--c-border-light)" }}>
        <table className="datagrid">
          <thead>
            <tr><th></th><th>Nazwa</th><th>Kod</th><th>Jm.</th><th>Typ</th></tr>
          </thead>
          <tbody>
            {candidates.map((product) => (
              <tr
                key={product.id}
                className="clickable"
                style={selectedId === product.id ? { background: "var(--c-blue-light)" } : undefined}
                onClick={() => setSelectedId(product.id)}
              >
                <td><input type="radio" readOnly checked={selectedId === product.id} /></td>
                <td>{product.name}</td>
                <td>{product.code ?? "—"}</td>
                <td>{product.unit ?? "—"}</td>
                <td>{product.kind}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Modal>
  );
}
