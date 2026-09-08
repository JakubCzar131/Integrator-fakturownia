import { STATUS_LABELS } from "../../lib/format";

const TONE_BY_STATUS: Record<string, string> = {
  OK: "ok", SUCCESS: "ok", RESOLVED: "ok", CONFIRMED: "ok", paid: "ok",
  LINKED: "ok",
  WARNING: "warn", PARTIAL: "warn", NEEDS_MAPPING: "warn", PROPOSED: "warn",
  NEEDS_OPENING_BALANCE: "warn", partial: "warn",
  MISSING: "warn", AMBIGUOUS: "warn", NO_REMOTE_STOCK: "warn",
  ERROR: "error", FAILED: "error", REJECTED: "error", CRITICAL: "error",
  HIGH: "error", cancelled: "error", DISCREPANCY: "error",
  RUNNING: "info", INCREMENTAL: "info", FULL: "info", MEDIUM: "warn",
  PENDING: "info", PENDING_CREATE: "info", DATABASE: "info",
  IGNORED: "neutral", LOW: "neutral", INFO: "info", issued: "info", sent: "info",
  EXCLUDED: "neutral", CANCELLED: "neutral", SKIPPED: "neutral",
  NEVER: "neutral", ENV: "neutral", NONE: "neutral",
};

export function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted">—</span>;
  const tone = TONE_BY_STATUS[value] ?? "neutral";
  return <span className={`badge badge--${tone}`}>{STATUS_LABELS[value] ?? value}</span>;
}
