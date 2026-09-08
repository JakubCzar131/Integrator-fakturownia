import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { PRODUCT_KIND_LABELS, formatQty } from "../../lib/format";
import type { InvoicePosition, Page, Product, ValidationIssue } from "../../lib/types";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { DetailTabs } from "../../components/erp/DetailTabs";
import { StatusBadge } from "../../components/erp/StatusBadge";
import { StockBalanceTable } from "../../components/erp/StockBalanceTable";
import { StockLedgerTable } from "../../components/erp/StockLedgerTable";
import { useToast } from "../../components/erp/Toast";
import { ValidationPanel } from "../../components/erp/ValidationPanel";
import { formatDate, formatMoney } from "../../lib/format";
import { ProductContentPanel } from "./ProductContentPanel";

function SalesHistory({ productId }: { productId: number }) {
  const [positions, setPositions] = useState<InvoicePosition[]>([]);
  useEffect(() => {
    api.get<Page<InvoicePosition>>(`/invoice-positions?product_id=${productId}&per_page=200`)
      .then((page) => setPositions(page.items))
      .catch(() => undefined);
  }, [productId]);
  return (
    <table className="datagrid">
      <thead>
        <tr>
          <th>Faktura</th><th>Data</th><th>Nabywca</th>
          <th className="num">Ilość</th><th>Jm.</th><th className="num">Wartość netto</th>
        </tr>
      </thead>
      <tbody>
        {positions.length === 0 && (
          <tr className="empty-row"><td colSpan={6}>Brak sprzedaży</td></tr>
        )}
        {positions.map((position) => (
          <tr key={position.id}>
            <td><Link to={`/invoices/${position.invoice_id}`}>{position.invoice_number}</Link></td>
            <td>{formatDate(position.invoice_issue_date)}</td>
            <td>{position.buyer_name ?? "—"}</td>
            <td className="num">{formatQty(position.quantity)}</td>
            <td>{position.quantity_unit ?? "—"}</td>
            <td className="num">{formatMoney(position.total_price_net)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ProductDetailPage() {
  const { id } = useParams();
  const productId = Number(id);
  const { canWrite } = useAuth();
  const toast = useToast();
  const [product, setProduct] = useState<Product | null>(null);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<{ kind: string; is_stock_controlled: boolean; is_active: boolean; notes: string }>({
    kind: "STOCK_ITEM", is_stock_controlled: true, is_active: true, notes: "",
  });

  const load = useCallback(() => {
    api.get<Product>(`/products/${productId}`).then((p) => {
      setProduct(p);
      setDraft({
        kind: p.kind, is_stock_controlled: p.is_stock_controlled,
        is_active: p.is_active, notes: p.notes ?? "",
      });
    }).catch(() => undefined);
    api.get<Page<ValidationIssue>>(`/validation/issues?product_id=${productId}&per_page=100`)
      .then((page) => setIssues(page.items))
      .catch(() => undefined);
  }, [productId]);

  useEffect(load, [load]);

  const saveClassification = async () => {
    try {
      await api.patch(`/products/${productId}`, draft);
      toast.success("Zapisano lokalną klasyfikację produktu");
      setEditing(false);
      load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd zapisu");
    }
  };

  if (!product) return <p className="text-muted">Ładowanie…</p>;

  return (
    <div>
      <ActionToolbar title={`Produkt: ${product.name}`}>
        <StatusBadge value={product.is_active ? "OK" : "ERROR"} />
        <span className="badge badge--info">{PRODUCT_KIND_LABELS[product.kind] ?? product.kind}</span>
        <span className="action-toolbar__spacer" />
        {canWrite && !editing && (
          <button className="btn" onClick={() => setEditing(true)}>Edytuj lokalnie</button>
        )}
        <Link className="btn" to="/products">← Lista produktów</Link>
      </ActionToolbar>

      <div className="panel">
        <div className="panel__header">Karta produktu (dane lokalne + Fakturownia)</div>
        <div className="panel__body">
          {!editing ? (
            <dl className="props">
              <div><dt>Nazwa</dt><dd>{product.name}</dd></div>
              <div><dt>Kod</dt><dd>{product.code ?? "—"}</dd></div>
              <div><dt>EAN</dt><dd>{product.ean ?? "—"}</dd></div>
              <div><dt>SKU</dt><dd>{product.sku ?? "—"}</dd></div>
              <div><dt>Jednostka</dt><dd>{product.unit ?? "—"}</dd></div>
              <div><dt>ID Fakturownia</dt><dd className="mono">{product.fakturownia_product_id ?? "— (produkt lokalny)"}</dd></div>
              <div><dt>Typ (lokalnie)</dt><dd>{PRODUCT_KIND_LABELS[product.kind] ?? product.kind}</dd></div>
              <div><dt>Kontrola magazynowa</dt><dd>{product.is_stock_controlled ? "Tak" : "Nie"}</dd></div>
              <div><dt>Stan lokalny (suma)</dt><dd>{formatQty(product.total_local_stock)}</dd></div>
              <div><dt>Stan wg Fakturowni</dt><dd>{formatQty(product.fakturownia_quantity)}</dd></div>
              {product.notes && <div><dt>Notatki</dt><dd>{product.notes}</dd></div>}
            </dl>
          ) : (
            <div className="form-grid">
              <div className="form-field">
                <label>Typ produktu (lokalna klasyfikacja)</label>
                <select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
                  {Object.entries(PRODUCT_KIND_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </div>
              <div className="form-field">
                <label>Kontrola magazynowa</label>
                <select
                  value={draft.is_stock_controlled ? "1" : "0"}
                  onChange={(e) => setDraft({ ...draft, is_stock_controlled: e.target.value === "1" })}
                >
                  <option value="1">Tak — kontroluj stany</option>
                  <option value="0">Nie — pomijaj w magazynie</option>
                </select>
              </div>
              <div className="form-field">
                <label>Aktywny</label>
                <select
                  value={draft.is_active ? "1" : "0"}
                  onChange={(e) => setDraft({ ...draft, is_active: e.target.value === "1" })}
                >
                  <option value="1">Tak</option>
                  <option value="0">Nie</option>
                </select>
              </div>
              <div className="form-field form-field--full">
                <label>Notatki (lokalne)</label>
                <textarea rows={2} value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />
              </div>
              <div className="form-field--full" style={{ display: "flex", gap: 6 }}>
                <button className="btn btn--primary" onClick={saveClassification}>Zapisz lokalnie</button>
                <button className="btn" onClick={() => setEditing(false)}>Anuluj</button>
              </div>
            </div>
          )}
        </div>
      </div>

      <DetailTabs
        tabs={[
          {
            key: "aliases", label: `Aliasy i mapowania (${product.aliases?.length ?? 0})`,
            content: (
              <div>
                <table className="datagrid">
                  <thead><tr><th>Typ aliasu</th><th>Wartość</th><th>Utworzono</th></tr></thead>
                  <tbody>
                    {(product.aliases ?? []).length === 0 && (
                      <tr className="empty-row"><td colSpan={3}>Brak aliasów</td></tr>
                    )}
                    {product.aliases?.map((alias) => (
                      <tr key={alias.id}>
                        <td>{alias.alias_type}</td>
                        <td>{alias.alias_value}</td>
                        <td>{formatDate(alias.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p style={{ marginTop: 8 }}>
                  <Link to={`/mappings?search=${encodeURIComponent(product.name)}`}>
                    Mapowania powiązane z tym produktem →
                  </Link>
                </p>
              </div>
            ),
          },
          { key: "sales", label: "Historia sprzedaży", content: <SalesHistory productId={productId} /> },
          { key: "ledger", label: "Ruchy magazynowe", content: <StockLedgerTable productId={productId} /> },
          {
            key: "receipts", label: "Przyjęcia PZ/PW",
            content: (
              <p>
                <Link to={`/warehouse-documents?product_id=${productId}`}>
                  Pozycje dokumentów przyjęć dla tego produktu →
                </Link>
              </p>
            ),
          },
          {
            key: "shop", label: "Treść dla sklepu (PIM)",
            content: <ProductContentPanel productId={productId} />,
          },
          { key: "stock", label: "Stany lokalne", content: <StockBalanceTable /> },
          {
            key: "validation", label: `Walidacja (${issues.length})`,
            content: <ValidationPanel issues={issues} onChanged={load} />,
          },
          ...(product.kind === "BUNDLE" ? [{
            key: "bundle", label: `Skład zestawu (${product.bundle_components?.length ?? 0})`,
            content: (
              <table className="datagrid">
                <thead><tr><th>Produkt składowy</th><th className="num">Ilość na zestaw</th></tr></thead>
                <tbody>
                  {(product.bundle_components ?? []).length === 0 && (
                    <tr className="empty-row"><td colSpan={2}>Brak zdefiniowanego składu — sprzedaż zestawu nie rozlicza magazynu</td></tr>
                  )}
                  {product.bundle_components?.map((component) => (
                    <tr key={component.id}>
                      <td>
                        <Link to={`/products/${component.component_product_id}`}>
                          {component.component_name ?? component.component_product_id}
                        </Link>
                      </td>
                      <td className="num">{formatQty(component.quantity)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ),
          }] : []),
        ]}
      />
    </div>
  );
}
