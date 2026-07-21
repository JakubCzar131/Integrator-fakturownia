import { useCallback, useEffect, useState } from "react";
import { api, buildQuery } from "./api";
import type { Page } from "./types";
import type { GridState } from "../components/datagrid/DataGrid";

export function usePagedData<T>(
  path: string,
  state: GridState,
  filters: Record<string, unknown>,
): { data: Page<T> | null; loading: boolean; error: string | null; reload: () => void } {
  const [data, setData] = useState<Page<T> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const filtersKey = JSON.stringify(filters);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const query = buildQuery({
      page: state.page,
      per_page: state.perPage,
      sort_by: state.sortBy ?? undefined,
      sort_dir: state.sortBy ? state.sortDir : undefined,
      ...JSON.parse(filtersKey),
    });
    api.get<Page<T>>(`${path}${query}`)
      .then((response) => {
        if (alive) { setData(response); setError(null); }
      })
      .catch((err) => alive && setError(err instanceof Error ? err.message : "Błąd pobierania"))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [path, state.page, state.perPage, state.sortBy, state.sortDir, filtersKey, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, loading, error, reload };
}
