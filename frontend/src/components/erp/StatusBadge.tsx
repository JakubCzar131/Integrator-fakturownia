import { STATUS_LABELS } from "../../lib/format";

const TONE_BY_STATUS: Record<string, string> = {
  OK: "ok", SUCCESS: "ok", RESOLVED: "ok", CONFIRMED: "ok", paid: "ok",
  WARNING: "warn", PARTIAL: "warn", NEEDS_MAPPING: "warn", PROPOSED: "warn",
  NEEDS_OPENING_BALANCE: "warn", partial: "warn",
  ERROR: "error", FAILED: "error", REJECTED: "error", CRITICAL: "error",
  HIGH: "error", cancelled: "error",
  RUNNING: "info", INCREMENTAL: "info", FULL: "info", MEDIUM: "warn",
  IGNORED: "neutral", LOW: "neutral", INFO: "info", issued: "info", sent: "info",
};

export function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted">—</span>;
  const tone = TONE_BY_STATUS[value] ?? "neutral";
  return <span className={`badge badge--${tone}`}>{STATUS_LABELS[value] ?? value}</span>;
}
