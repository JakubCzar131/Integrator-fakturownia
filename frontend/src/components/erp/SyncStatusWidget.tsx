import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import type { SyncStatus } from "../../lib/types";
import { StatusBadge } from "./StatusBadge";

export function SyncStatusWidget() {
  const [status, setStatus] = useState<SyncStatus | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api.get<SyncStatus>("/sync/status").then((s) => alive && setStatus(s)).catch(() => undefined);
    load();
    const interval = setInterval(load, 15000);
    return () => { alive = false; clearInterval(interval); };
  }, []);

  if (!status) return null;
  return (
    <div className="topbar__sync" title="Status synchronizacji z Fakturownią (tylko odczyt)">
      {status.in_progress ? (
        <><span className="spinner" /> Synchronizacja w toku…</>
      ) : status.last_run ? (
        <>
          Ost. synchronizacja: {formatDateTime(status.last_run.finished_at ?? status.last_run.started_at)}
          <StatusBadge value={status.last_run.status} />
        </>
      ) : (
        <span>Brak synchronizacji</span>
      )}
    </div>
  );
}
