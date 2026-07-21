/**
 * ValidationPanel — lista problemów walidacyjnych z akcjami operatora
 * (zmiana statusu, komentarze). Używany w widoku faktury i module Walidacje.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { ISSUE_TYPE_LABELS, formatDateTime, formatQty } from "../../lib/format";
import type { ValidationIssue } from "../../lib/types";
import { StatusBadge } from "./StatusBadge";
import { useToast } from "./Toast";

const STATUS_OPTIONS = ["ERROR", "WARNING", "NEEDS_MAPPING", "NEEDS_OPENING_BALANCE", "IGNORED", "RESOLVED", "OK"];

export function ValidationPanel({
  issues, onChanged,
}: { issues: ValidationIssue[]; onChanged: () => void }) {
  const { canWrite } = useAuth();
  const toast = useToast();
  const [commentDrafts, setCommentDrafts] = useState<Record<number, string>>({});
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const changeStatus = async (issue: ValidationIssue, status: string) => {
    try {
      await api.patch(`/validation/issues/${issue.id}`, { status });
      toast.success(`Status problemu #${issue.id} zmieniony na ${status}`);
      onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd zmiany statusu");
    }
  };

  const addComment = async (issue: ValidationIssue) => {
    const body = commentDrafts[issue.id]?.trim();
    if (!body) return;
    try {
      await api.post(`/validation/issues/${issue.id}/comments`, { body });
      setCommentDrafts((drafts) => ({ ...drafts, [issue.id]: "" }));
      toast.success("Komentarz dodany");
      onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd dodawania komentarza");
    }
  };

  const toggle = (id: number) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (issues.length === 0) {
    return <p className="text-muted">Brak problemów walidacyjnych.</p>;
  }

  return (
    <div>
      {issues.map((issue) => (
        <div className="panel" key={issue.id}>
          <div className="panel__header" style={{ cursor: "pointer" }} onClick={() => toggle(issue.id)}>
            <StatusBadge value={issue.severity} />
            <StatusBadge value={issue.status} />
            <span>#{issue.id} · {ISSUE_TYPE_LABELS[issue.issue_type] ?? issue.issue_type}</span>
            <span className="text-muted" style={{ fontWeight: 400 }}>
              {issue.business_description}
            </span>
            <span style={{ marginLeft: "auto" }}>{expanded.has(issue.id) ? "▴" : "▾"}</span>
          </div>
          {expanded.has(issue.id) && (
            <div className="panel__body">
              <dl className="props">
                {issue.invoice_number && (
                  <div><dt>Faktura</dt><dd>
                    <Link to={`/invoices/${issue.invoice_id}`}>{issue.invoice_number}</Link>
                  </dd></div>
                )}
                {issue.product_name && (
                  <div><dt>Produkt</dt><dd>
                    <Link to={`/products/${issue.product_id}`}>{issue.product_name}</Link>
                  </dd></div>
                )}
                {issue.warehouse_name && <div><dt>Magazyn</dt><dd>{issue.warehouse_name}</dd></div>}
                {issue.quantity !== null && <div><dt>Ilość</dt><dd>{formatQty(issue.quantity)}</dd></div>}
                {issue.stock_before !== null && (
                  <div><dt>Stan przed</dt><dd>{formatQty(issue.stock_before)}</dd></div>
                )}
                {issue.stock_after !== null && (
                  <div><dt>Stan po</dt><dd>{formatQty(issue.stock_after)}</dd></div>
                )}
                <div><dt>Utworzono</dt><dd>{formatDateTime(issue.created_at)}</dd></div>
                {issue.resolved_at && (
                  <div><dt>Rozwiązano</dt><dd>{formatDateTime(issue.resolved_at)}</dd></div>
                )}
              </dl>
              {issue.recommended_action && (
                <p><b>Rekomendowana akcja:</b> {issue.recommended_action}</p>
              )}
              {issue.technical_description && (
                <p className="mono text-muted">{issue.technical_description}</p>
              )}
              {canWrite && (
                <p>
                  <b>Zmień status: </b>
                  {STATUS_OPTIONS.filter((s) => s !== issue.status).map((status) => (
                    <button
                      key={status}
                      className="btn btn--small"
                      style={{ marginRight: 4 }}
                      onClick={() => changeStatus(issue, status)}
                    >
                      {status}
                    </button>
                  ))}
                </p>
              )}
              <div>
                <b>Komentarze ({issue.comments.length})</b>
                <ul className="timeline">
                  {issue.comments.map((comment) => (
                    <li key={comment.id}>
                      <div>{comment.body}</div>
                      <div className="timeline__meta">
                        {formatDateTime(comment.created_at)} · {comment.user_email ?? "—"}
                      </div>
                    </li>
                  ))}
                </ul>
                {canWrite && (
                  <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                    <input
                      style={{ flex: 1, height: 26, border: "1px solid var(--c-border)", borderRadius: 3, padding: "0 6px" }}
                      placeholder="Dodaj komentarz (lokalnie)…"
                      value={commentDrafts[issue.id] ?? ""}
                      onChange={(e) =>
                        setCommentDrafts((drafts) => ({ ...drafts, [issue.id]: e.target.value }))}
                      onKeyDown={(e) => e.key === "Enter" && addComment(issue)}
                    />
                    <button className="btn btn--small" onClick={() => addComment(issue)}>Dodaj</button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
