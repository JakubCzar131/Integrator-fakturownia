import { useCallback, useEffect, useState } from "react";
import { api, buildQuery } from "../../lib/api";
import type { ReportResult } from "../../lib/types";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { FilterBar, FilterField } from "../../components/erp/FilterBar";
import { useToast } from "../../components/erp/Toast";

const REPORTS = [
  { key: "sales", label: "Sprzedaż produktów wg okresu", hasDates: true },
  { key: "unmapped-products", label: "Produkty sprzedane bez mapowania" },
  { key: "negative-stock", label: "Produkty ze stanem ujemnym" },
  { key: "stock-discrepancies", label: "Różnice magazynowe (lokalny vs Fakturownia)" },
  { key: "stock-history", label: "Historia stanów magazynowych" },
  { key: "problem-invoices", label: "Faktury z problemami" },
  { key: "top-error-products", label: "Produkty najczęściej powodujące błędy" },
];

export function ReportsPage() {
  const toast = useToast();
  const [reportKey, setReportKey] = useState("sales");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [result, setResult] = useState<ReportResult | null>(null);
  const [loading, setLoading] = useState(false);

  const definition = REPORTS.find((r) => r.key === reportKey)!;

  const load = useCallback(() => {
    setLoading(true);
    const query = buildQuery({
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    });
    api.get<ReportResult>(`/reports/${reportKey}${query}`)
      .then(setResult)
      .catch((error) => toast.error(error instanceof Error ? error.message : "Błąd raportu"))
      .finally(() => setLoading(false));
  }, [reportKey, dateFrom, dateTo, toast]);

  useEffect(load, [load]);

  const download = async (format: "csv" | "xlsx" | "pdf") => {
    try {
      const query = buildQuery({
        format,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      await api.download(`/reports/${reportKey}${query}`, `${reportKey}.${format}`);
      toast.success(`Raport wyeksportowany (${format.toUpperCase()})`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd eksportu");
    }
  };

  return (
    <div>
      <ActionToolbar title="Raporty">
        <button className="btn" onClick={() => download("csv")}>Eksport CSV</button>
        <button className="btn" onClick={() => download("xlsx")}>Eksport XLSX</button>
        <button className="btn" onClick={() => download("pdf")}>Eksport PDF</button>
        <span className="action-toolbar__spacer" />
        <button className="btn" onClick={load}>Odśwież</button>
      </ActionToolbar>
      <FilterBar>
        <FilterField label="Raport">
          <select value={reportKey} onChange={(e) => setReportKey(e.target.value)} style={{ width: 320 }}>
            {REPORTS.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
          </select>
        </FilterField>
        {definition.hasDates && (
          <>
            <FilterField label="Data od">
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
            </FilterField>
            <FilterField label="Data do">
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
            </FilterField>
          </>
        )}
        <span style={{ flex: 1 }} />
        <span className="text-muted">Wierszy: {result?.row_count ?? 0}</span>
      </FilterBar>
      <div className="datagrid-container">
        <div className="datagrid-scroll" style={{ maxHeight: "65vh" }}>
          <table className="datagrid">
            <thead>
              <tr>{result?.headers.map((header) => <th key={header}>{header}</th>)}</tr>
            </thead>
            <tbody>
              {loading && (
                <tr className="empty-row"><td colSpan={result?.headers.length ?? 1}>Ładowanie…</td></tr>
              )}
              {!loading && result?.rows.length === 0 && (
                <tr className="empty-row"><td colSpan={result.headers.length}>Brak danych</td></tr>
              )}
              {!loading && result?.rows.map((row, index) => (
                <tr key={index}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex} className={typeof cell === "number" ? "num" : undefined}>
                      {cell === null || cell === "" ? "—" : String(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
