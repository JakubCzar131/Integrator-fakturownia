/**
 * DataGrid — centralny komponent tabelaryczny ERP.
 *
 * Funkcje: sortowanie po kolumnach (server-side), paginacja, wybór kolumn
 * z zapamiętywaniem preferencji per użytkownik (backend), gęste wiersze,
 * klik wiersza -> nawigacja do szczegółu.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../../lib/api";
import type { Page } from "../../lib/types";

export interface ColumnDef<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  sortable?: boolean;
  numeric?: boolean;
  defaultHidden?: boolean;
  cellClass?: (row: T) => string | undefined;
}

export interface GridState {
  page: number;
  perPage: number;
  sortBy: string | null;
  sortDir: "asc" | "desc";
}

interface DataGridProps<T> {
  tableKey: string;
  columns: ColumnDef<T>[];
  data: Page<T> | null;
  loading?: boolean;
  state: GridState;
  onStateChange: (state: GridState) => void;
  onRowClick?: (row: T) => void;
  rowKey: (row: T) => string | number;
  footerExtra?: ReactNode;
}

const PER_PAGE_OPTIONS = [25, 50, 100, 200];

export function useGridState(initial?: Partial<GridState>): [GridState, (s: GridState) => void] {
  const [state, setState] = useState<GridState>({
    page: 1, perPage: 50, sortBy: null, sortDir: "asc", ...initial,
  });
  return [state, setState];
}

export function DataGrid<T>({
  tableKey, columns, data, loading, state, onStateChange, onRowClick, rowKey, footerExtra,
}: DataGridProps<T>) {
  const [hidden, setHidden] = useState<Set<string>>(
    () => new Set(columns.filter((c) => c.defaultHidden).map((c) => c.key)),
  );
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);
  const prefsLoaded = useRef(false);

  useEffect(() => {
    api.get<{ columns: { hidden?: string[] } | null }>(
      `/settings/column-preferences/${tableKey}`,
    )
      .then((response) => {
        if (response.columns?.hidden) setHidden(new Set(response.columns.hidden));
      })
      .catch(() => undefined)
      .finally(() => { prefsLoaded.current = true; });
  }, [tableKey]);

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(event.target as Node)) {
        setPickerOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const toggleColumn = (key: string) => {
    const next = new Set(hidden);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setHidden(next);
    if (prefsLoaded.current) {
      api.put("/settings/column-preferences", {
        table_key: tableKey,
        columns: { hidden: Array.from(next) },
      }).catch(() => undefined);
    }
  };

  const visibleColumns = useMemo(
    () => columns.filter((c) => !hidden.has(c.key)),
    [columns, hidden],
  );

  const handleSort = (column: ColumnDef<T>) => {
    if (!column.sortable) return;
    if (state.sortBy === column.key) {
      onStateChange({ ...state, sortDir: state.sortDir === "asc" ? "desc" : "asc", page: 1 });
    } else {
      onStateChange({ ...state, sortBy: column.key, sortDir: "asc", page: 1 });
    }
  };

  const totalPages = data?.pages ?? 1;
  const setPage = (page: number) =>
    onStateChange({ ...state, page: Math.min(Math.max(1, page), totalPages) });

  return (
    <div className="datagrid-container">
      <div className="datagrid-scroll">
        <table className="datagrid">
          <thead>
            <tr>
              {visibleColumns.map((column) => (
                <th
                  key={column.key}
                  className={`${column.sortable ? "sortable" : ""} ${column.numeric ? "num" : ""}`}
                  onClick={() => handleSort(column)}
                >
                  {column.header}
                  {state.sortBy === column.key && (
                    <span className="sort-arrow">{state.sortDir === "asc" ? "▲" : "▼"}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr className="empty-row"><td colSpan={visibleColumns.length}>
                <span className="spinner spinner--dark" /> Ładowanie…
              </td></tr>
            )}
            {!loading && (!data || data.items.length === 0) && (
              <tr className="empty-row"><td colSpan={visibleColumns.length}>Brak danych</td></tr>
            )}
            {!loading && data?.items.map((row) => (
              <tr
                key={rowKey(row)}
                className={onRowClick ? "clickable" : undefined}
                onClick={() => onRowClick?.(row)}
              >
                {visibleColumns.map((column) => (
                  <td
                    key={column.key}
                    className={`${column.numeric ? "num" : ""} ${column.cellClass?.(row) ?? ""}`}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="datagrid-footer">
        <span>
          Wierszy: <b>{data?.total ?? 0}</b>
        </span>
        <select
          value={state.perPage}
          onChange={(e) => onStateChange({ ...state, perPage: Number(e.target.value), page: 1 })}
        >
          {PER_PAGE_OPTIONS.map((n) => <option key={n} value={n}>{n} / str.</option>)}
        </select>
        <div className="pages">
          <button className="btn btn--small" disabled={state.page <= 1} onClick={() => setPage(1)}>«</button>
          <button className="btn btn--small" disabled={state.page <= 1} onClick={() => setPage(state.page - 1)}>‹</button>
          <span style={{ padding: "0 6px" }}>str. {state.page} / {totalPages}</span>
          <button className="btn btn--small" disabled={state.page >= totalPages} onClick={() => setPage(state.page + 1)}>›</button>
          <button className="btn btn--small" disabled={state.page >= totalPages} onClick={() => setPage(totalPages)}>»</button>
        </div>
        {footerExtra}
        <span style={{ flex: 1 }} />
        <div className="colpicker" ref={pickerRef}>
          <button className="btn btn--small" onClick={() => setPickerOpen(!pickerOpen)}>
            Kolumny ▾
          </button>
          {pickerOpen && (
            <div className="colpicker__menu">
              {columns.map((column) => (
                <label key={column.key}>
                  <input
                    type="checkbox"
                    checked={!hidden.has(column.key)}
                    onChange={() => toggleColumn(column.key)}
                  />
                  {column.header}
                </label>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
