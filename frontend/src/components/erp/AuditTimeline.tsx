import { formatDateTime } from "../../lib/format";
import type { AuditLogEntry } from "../../lib/types";

export function AuditTimeline({ entries }: { entries: AuditLogEntry[] }) {
  if (entries.length === 0) {
    return <p className="text-muted">Brak wpisów audytu.</p>;
  }
  return (
    <ul className="timeline">
      {entries.map((entry) => (
        <li key={entry.id}>
          <div>{entry.description ?? `${entry.action} ${entry.object_type ?? ""}`}</div>
          <div className="timeline__meta">
            {formatDateTime(entry.created_at)} · {entry.user_email ?? "system"} · {entry.action}
            {entry.ip_address ? ` · ${entry.ip_address}` : ""}
          </div>
        </li>
      ))}
    </ul>
  );
}
