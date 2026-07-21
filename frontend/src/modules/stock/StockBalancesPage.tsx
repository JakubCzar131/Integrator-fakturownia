/**
 * Moduł „Stany magazynowe”: tabela stanów + stany początkowe + korekty lokalne
 * + przeliczenie stanów. Wszystkie operacje wyłącznie lokalne.
 */
import { useEffect, useState } from "react";
import { api, buildQuery } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatDate, formatDateTime, formatQty } from "../../lib/format";
import type { OpeningBalance, Page, Product, StockAdjustment, Warehouse } from "../../lib/types";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { DetailTabs } from "../../components/erp/DetailTabs";
import { Modal, ConfirmModal } from "../../components/erp/Modal";
import { StockBalanceTable } from "../../components/erp/StockBalanceTable";
import { useToast } from "../../components/erp/Toast";

function ProductSelect({
  value, onChange,
}: { value: number | null; onChange: (id: number) => void }) {
  const [search, setSearch] = useState("");
  const [options, setOptions] = useState<Product[]>([]);
  useEffect(() => {
    const timer = setTimeout(() => {
      api.get<Page<Product>>(`/products${buildQuery({ search: search || undefined, per_page: 30 })}`)
        .then((page) => setOptions(page.items))
        .catch(() => undefined);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);
  return (
    <div className="form-field form-field--full">
      <label>Produkt</label>
      <input placeholder="szukaj produktu…" value={search} onChange={(e) => setSearch(e.target.value)} />
      <select size={5} value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))} style={{ height: "auto" }}>
        {options.map((product) => (
          <option key={product.id} value={product.id}>
            {product.name} {product.code ? `[${product.code}]` : ""}
          </option>
        ))}
      </select>
    </div>
  );
}

function OpeningBalanceModal({ warehouses, onClose, onSaved }: {
  warehouses: Warehouse[]; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const [productId, setProductId] = useState<number | null>(null);
  const [warehouseId, setWarehouseId] = useState<number>(warehouses[0]?.id ?? 1);
  const [quantity, setQuantity] = useState("0");
  const [asOfDate, setAsOfDate] = useState(new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState("");

  const save = async () => {
    if (!productId) { toast.error("Wybierz produkt"); return; }
    try {
      await api.post("/stock/opening-balances", {
        product_id: productId, warehouse_id: warehouseId,
        quantity, as_of_date: asOfDate, note: note || null,
      });
      toast.success("Stan początkowy zapisany (lokalnie) i stany przeliczone");
      onSaved();
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd zapisu");
    }
  };

  return (
    <Modal
      title="Ustaw lokalny stan początkowy"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Anuluj</button>
          <button className="btn btn--primary" onClick={save}>Zapisz lokalnie</button>
        </>
      }
    >
      <div className="form-grid">
        <ProductSelect value={productId} onChange={setProductId} />
        <div className="form-field">
          <label>Magazyn</label>
          <select value={warehouseId} onChange={(e) => setWarehouseId(Number(e.target.value))}>
            {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </div>
        <div className="form-field">
          <label>Ilość</label>
          <input type="number" step="0.0001" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </div>
        <div className="form-field">
          <label>Stan na dzień</label>
          <input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} />
        </div>
        <div className="form-field form-field--full">
          <label>Notatka</label>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="np. inwentaryzacja 01.01" />
        </div>
      </div>
    </Modal>
  );
}

function AdjustmentModal({ warehouses, onClose, onSaved }: {
  warehouses: Warehouse[]; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const [productId, setProductId] = useState<number | null>(null);
  const [warehouseId, setWarehouseId] = useState<number>(warehouses[0]?.id ?? 1);
  const [quantityChange, setQuantityChange] = useState("0");
  const [description, setDescription] = useState("");

  const save = async () => {
    if (!productId) { toast.error("Wybierz produkt"); return; }
    if (description.trim().length < 3) { toast.error("Opis korekty jest wymagany"); return; }
    try {
      await api.post("/stock/local-adjustments", {
        product_id: productId, warehouse_id: warehouseId,
        quantity_change: quantityChange, description,
      });
      toast.success("Korekta lokalna zapisana i stany przeliczone");
      onSaved();
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd zapisu");
    }
  };

  return (
    <Modal
      title="Dodaj lokalną korektę magazynową"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Anuluj</button>
          <button className="btn btn--primary" onClick={save}>Zapisz lokalnie</button>
        </>
      }
    >
      <div className="form-grid">
        <ProductSelect value={productId} onChange={setProductId} />
        <div className="form-field">
          <label>Magazyn</label>
          <select value={warehouseId} onChange={(e) => setWarehouseId(Number(e.target.value))}>
            {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </div>
        <div className="form-field">
          <label>Zmiana ilości (+/−)</label>
          <input type="number" step="0.0001" value={quantityChange} onChange={(e) => setQuantityChange(e.target.value)} />
        </div>
        <div className="form-field form-field--full">
          <label>Opis / powód (wymagany, trafia do audytu)</label>
          <textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
      </div>
    </Modal>
  );
}

function OpeningBalancesTab({ reloadKey }: { reloadKey: number }) {
  const [rows, setRows] = useState<OpeningBalance[]>([]);
  useEffect(() => {
    api.get<Page<OpeningBalance>>("/stock/opening-balances?per_page=200")
      .then((page) => setRows(page.items)).catch(() => undefined);
  }, [reloadKey]);
  return (
    <table className="datagrid">
      <thead>
        <tr><th>Produkt</th><th>Magazyn</th><th className="num">Ilość</th><th>Na dzień</th><th>Notatka</th><th>Utworzono</th></tr>
      </thead>
      <tbody>
        {rows.length === 0 && <tr className="empty-row"><td colSpan={6}>Brak stanów początkowych</td></tr>}
        {rows.map((row) => (
          <tr key={row.id}>
            <td>{row.product_name}</td>
            <td>{row.warehouse_name}</td>
            <td className="num">{formatQty(row.quantity)}</td>
            <td>{formatDate(row.as_of_date)}</td>
            <td>{row.note ?? "—"}</td>
            <td>{formatDateTime(row.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AdjustmentsTab({ reloadKey, onReverted }: { reloadKey: number; onReverted: () => void }) {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [rows, setRows] = useState<StockAdjustment[]>([]);
  const [confirmId, setConfirmId] = useState<number | null>(null);

  useEffect(() => {
    api.get<Page<StockAdjustment>>("/stock/local-adjustments?per_page=200")
      .then((page) => setRows(page.items)).catch(() => undefined);
  }, [reloadKey]);

  const reverse = async (id: number) => {
    try {
      await api.post(`/stock/local-adjustments/${id}/reverse`);
      toast.success("Storno zapisane — historia pozostaje nienaruszona");
      onReverted();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd storna");
    }
  };

  return (
    <>
      <table className="datagrid">
        <thead>
          <tr>
            <th>#</th><th>Produkt</th><th>Magazyn</th><th className="num">Zmiana</th>
            <th>Opis</th><th>Data operacji</th><th>Storno</th><th></th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr className="empty-row"><td colSpan={8}>Brak korekt lokalnych</td></tr>}
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{row.id}</td>
              <td>{row.product_name}</td>
              <td>{row.warehouse_name}</td>
              <td className={`num ${parseFloat(row.quantity_change) < 0 ? "negative" : ""}`}>
                {formatQty(row.quantity_change)}
              </td>
              <td>{row.description}</td>
              <td>{formatDateTime(row.occurred_at)}</td>
              <td>{row.is_reversal ? `storno #${row.reverses_adjustment_id}` : "—"}</td>
              <td>
                {canWrite && !row.is_reversal && (
                  <button className="btn btn--small" onClick={() => setConfirmId(row.id)}>Stornuj</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {confirmId !== null && (
        <ConfirmModal
          title="Storno korekty"
          message={`Czy na pewno wykonać storno korekty #${confirmId}? Powstanie korekta odwrotna (historia nie jest usuwana).`}
          confirmLabel="Wykonaj storno"
          onConfirm={() => reverse(confirmId)}
          onClose={() => setConfirmId(null)}
        />
      )}
    </>
  );
}

export function StockBalancesPage() {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [showOpeningModal, setShowOpeningModal] = useState(false);
  const [showAdjustmentModal, setShowAdjustmentModal] = useState(false);
  const [confirmRecalc, setConfirmRecalc] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    api.get<Warehouse[]>("/warehouses").then(setWarehouses).catch(() => undefined);
  }, []);

  const recalculate = async () => {
    try {
      const result = await api.post<{ message: string }>("/stock/recalculate");
      toast.success(result.message);
      setReloadKey((k) => k + 1);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd przeliczenia");
    }
  };

  return (
    <div>
      <ActionToolbar title="Stany magazynowe (lokalne)">
        {canWrite && (
          <>
            <button className="btn" onClick={() => setShowOpeningModal(true)}>+ Stan początkowy</button>
            <button className="btn" onClick={() => setShowAdjustmentModal(true)}>+ Korekta lokalna</button>
            <button className="btn btn--primary" onClick={() => setConfirmRecalc(true)}>
              ⟳ Przelicz stany od nowa
            </button>
          </>
        )}
      </ActionToolbar>
      <DetailTabs
        key={reloadKey}
        tabs={[
          { key: "balances", label: "Tabela stanów", content: <StockBalanceTable /> },
          { key: "opening", label: "Stany początkowe", content: <OpeningBalancesTab reloadKey={reloadKey} /> },
          {
            key: "adjustments", label: "Korekty lokalne",
            content: <AdjustmentsTab reloadKey={reloadKey} onReverted={() => setReloadKey((k) => k + 1)} />,
          },
        ]}
      />
      {showOpeningModal && (
        <OpeningBalanceModal
          warehouses={warehouses}
          onClose={() => setShowOpeningModal(false)}
          onSaved={() => setReloadKey((k) => k + 1)}
        />
      )}
      {showAdjustmentModal && (
        <AdjustmentModal
          warehouses={warehouses}
          onClose={() => setShowAdjustmentModal(false)}
          onSaved={() => setReloadKey((k) => k + 1)}
        />
      )}
      {confirmRecalc && (
        <ConfirmModal
          title="Przeliczenie stanów"
          message="Ledger i salda zostaną przebudowane od zera na podstawie stanów początkowych, faktur i korekt lokalnych. Operacja jest w pełni lokalna. Kontynuować?"
          confirmLabel="Przelicz"
          onConfirm={recalculate}
          onClose={() => setConfirmRecalc(false)}
        />
      )}
    </div>
  );
}
