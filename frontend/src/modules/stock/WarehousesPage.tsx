import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import type { Warehouse } from "../../lib/types";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { DetailTabs } from "../../components/erp/DetailTabs";
import { StockBalanceTable } from "../../components/erp/StockBalanceTable";
import { StockLedgerTable } from "../../components/erp/StockLedgerTable";

export function WarehousesPage() {
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  useEffect(() => {
    api.get<Warehouse[]>("/warehouses").then((list) => {
      setWarehouses(list);
      if (list.length > 0) setSelectedId(list[0].id);
    }).catch(() => undefined);
  }, []);

  const selected = warehouses.find((w) => w.id === selectedId) ?? null;

  return (
    <div>
      <ActionToolbar title="Magazyny" />
      <div className="panel">
        <div className="panel__body" style={{ padding: 0 }}>
          <table className="datagrid">
            <thead>
              <tr>
                <th>Nazwa</th><th>Źródło</th><th>Typ</th>
                <th className="num">Pozycji ze stanem</th>
                <th className="num">Stany ujemne</th>
                <th>Domyślny</th>
              </tr>
            </thead>
            <tbody>
              {warehouses.map((warehouse) => (
                <tr
                  key={warehouse.id}
                  className="clickable"
                  style={selectedId === warehouse.id ? { background: "var(--c-blue-light)" } : undefined}
                  onClick={() => setSelectedId(warehouse.id)}
                >
                  <td><b>{warehouse.name}</b></td>
                  <td>{warehouse.fakturownia_id ? `Fakturownia #${warehouse.fakturownia_id}` : "Lokalny"}</td>
                  <td>{warehouse.kind ?? "—"}</td>
                  <td className="num">{warehouse.product_count}</td>
                  <td className={`num ${warehouse.negative_count > 0 ? "negative" : ""}`}>
                    {warehouse.negative_count}
                  </td>
                  <td>{warehouse.is_default ? "✓" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selected && (
        <DetailTabs
          tabs={[
            {
              key: "balances", label: `Stany — ${selected.name}`,
              content: <StockBalanceTable warehouseId={selected.id} />,
            },
            {
              key: "ledger", label: "Ruchy magazynowe",
              content: <StockLedgerTable warehouseId={selected.id} />,
            },
          ]}
        />
      )}
    </div>
  );
}
