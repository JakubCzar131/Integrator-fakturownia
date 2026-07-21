import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { StockLedgerTable } from "../../components/erp/StockLedgerTable";

export function StockLedgerPage() {
  return (
    <div>
      <ActionToolbar title="Ruchy magazynowe — pełny ledger (lokalny)" />
      <StockLedgerTable />
    </div>
  );
}
