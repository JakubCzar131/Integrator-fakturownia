import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import { formatDate, formatDateTime, formatMoney, formatQty } from "../../lib/format";
import type { AuditLogEntry, Invoice, Page, ValidationIssue } from "../../lib/types";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { AuditTimeline } from "../../components/erp/AuditTimeline";
import { DetailTabs } from "../../components/erp/DetailTabs";
import { StatusBadge } from "../../components/erp/StatusBadge";
import { StockLedgerTable } from "../../components/erp/StockLedgerTable";
import { ValidationPanel } from "../../components/erp/ValidationPanel";

export function InvoiceDetailPage() {
  const { id } = useParams();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [audit, setAudit] = useState<AuditLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!id) return;
    api.get<Invoice>(`/invoices/${id}`).then(setInvoice).catch((e) => setError(e.message));
    api.get<ValidationIssue[]>(`/invoices/${id}/issues`).then(setIssues).catch(() => undefined);
    api.get<Page<AuditLogEntry>>(`/audit-log?object_type=validation_issue&per_page=50`)
      .then((page) => setAudit(page.items))
      .catch(() => undefined);
  }, [id]);

  useEffect(load, [load]);

  if (error) return <p className="form-error">{error}</p>;
  if (!invoice) return <p className="text-muted">Ładowanie…</p>;

  const positionIssueCount = new Map<number, number>();
  for (const issue of issues) {
    if (issue.invoice_position_id && !["RESOLVED", "IGNORED", "OK"].includes(issue.status)) {
      positionIssueCount.set(
        issue.invoice_position_id,
        (positionIssueCount.get(issue.invoice_position_id) ?? 0) + 1,
      );
    }
  }

  const positionsTable = (
    <table className="datagrid">
      <thead>
        <tr>
          <th>Lp.</th><th>Nazwa</th><th>Kod</th>
          <th className="num">Ilość</th><th>Jm.</th>
          <th className="num">Cena netto</th><th className="num">Wartość netto</th>
          <th>VAT</th><th>Mapowanie</th><th>Problemy</th>
        </tr>
      </thead>
      <tbody>
        {invoice.positions?.map((position, index) => (
          <tr key={position.id} style={positionIssueCount.get(position.id) ? { background: "var(--c-error-bg)" } : undefined}>
            <td>{index + 1}</td>
            <td>
              {position.mapped_product_id
                ? <Link to={`/products/${position.mapped_product_id}`}>{position.name}</Link>
                : position.name}
            </td>
            <td>{position.code ?? "—"}</td>
            <td className="num">{formatQty(position.quantity)}</td>
            <td>{position.quantity_unit ?? "—"}</td>
            <td className="num">{formatMoney(position.price_net)}</td>
            <td className="num">{formatMoney(position.total_price_net)}</td>
            <td>{position.tax ?? "—"}</td>
            <td><StatusBadge value={position.mapping_status ?? undefined} /></td>
            <td>
              {positionIssueCount.get(position.id)
                ? <span className="badge badge--error">{positionIssueCount.get(position.id)}</span>
                : <span className="badge badge--ok">OK</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <div>
      <ActionToolbar title={`Faktura ${invoice.number ?? invoice.fakturownia_id}`}>
        <StatusBadge value={invoice.is_cancelled ? "cancelled" : invoice.invoice_status ?? undefined} />
        {invoice.is_correction && <span className="badge badge--info">Korekta</span>}
        {invoice.is_deleted_upstream && <span className="badge badge--error">Usunięta w Fakturowni</span>}
        {invoice.open_issue_count > 0 && (
          <span className="badge badge--error">{invoice.open_issue_count} problemów</span>
        )}
        <span className="action-toolbar__spacer" />
        <Link className="btn" to="/invoices">← Lista faktur</Link>
      </ActionToolbar>

      <div className="panel">
        <div className="panel__body">
          <dl className="props">
            <div><dt>Numer</dt><dd>{invoice.number}</dd></div>
            <div><dt>ID Fakturownia</dt><dd className="mono">{invoice.fakturownia_id}</dd></div>
            <div><dt>Typ</dt><dd>{invoice.kind}</dd></div>
            <div><dt>Data wystawienia</dt><dd>{formatDate(invoice.issue_date)}</dd></div>
            <div><dt>Data sprzedaży</dt><dd>{formatDate(invoice.sell_date)}</dd></div>
            <div><dt>Nabywca</dt><dd>{invoice.buyer_name}</dd></div>
            <div><dt>NIP</dt><dd>{invoice.buyer_tax_no ?? "—"}</dd></div>
            <div><dt>Netto</dt><dd>{formatMoney(invoice.total_net)} {invoice.currency}</dd></div>
            <div><dt>Brutto</dt><dd>{formatMoney(invoice.total_gross)} {invoice.currency}</dd></div>
            <div><dt>Zapłacono</dt><dd>{formatMoney(invoice.paid_amount)}</dd></div>
            {invoice.corrected_invoice_fakturownia_id && (
              <div><dt>Koryguje dokument</dt><dd className="mono">{invoice.corrected_invoice_fakturownia_id}</dd></div>
            )}
            <div><dt>Ost. synchronizacja</dt><dd>{formatDateTime(invoice.last_synced_at)}</dd></div>
          </dl>
        </div>
      </div>

      <DetailTabs
        tabs={[
          { key: "positions", label: `Pozycje (${invoice.positions?.length ?? 0})`, content: positionsTable },
          {
            key: "validation", label: `Walidacja (${issues.length})`,
            content: <ValidationPanel issues={issues} onChanged={load} />,
          },
          { key: "history", label: "Historia", content: <AuditTimeline entries={audit} /> },
          {
            key: "raw", label: "Surowe dane z Fakturowni",
            content: <pre className="raw-json">{JSON.stringify(invoice.raw, null, 2)}</pre>,
          },
          {
            key: "ledger", label: "Powiązane ruchy magazynowe",
            content: <StockLedgerTable invoiceId={invoice.id} />,
          },
        ]}
      />
    </div>
  );
}
