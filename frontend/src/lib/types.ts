// Typy odpowiadające schematom API backendu.

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface UserInfo {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
  role_names: string[];
}

export interface SyncRun {
  id: number;
  run_type: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  records_fetched: number;
  records_created: number;
  records_updated: number;
  records_unchanged: number;
  error_count: number;
  stats: Record<string, unknown> | null;
  errors: string[] | null;
  message: string | null;
}

export interface SyncStatus {
  in_progress: boolean;
  last_run: SyncRun | null;
  last_success: SyncRun | null;
}

export interface InvoicePosition {
  id: number;
  fakturownia_id: number | null;
  invoice_id: number;
  product_fakturownia_id: number | null;
  name: string | null;
  code: string | null;
  quantity: string | null;
  quantity_unit: string | null;
  price_net: string | null;
  price_gross: string | null;
  total_price_net: string | null;
  total_price_gross: string | null;
  tax: string | null;
  mapped_product_id: number | null;
  mapping_status: string | null;
  mapping_match_type: string | null;
  invoice_number?: string | null;
  invoice_issue_date?: string | null;
  invoice_kind?: string | null;
  buyer_name?: string | null;
  open_issue_count?: number;
}

export interface Invoice {
  id: number;
  fakturownia_id: number;
  number: string | null;
  kind: string | null;
  invoice_status: string | null;
  issue_date: string | null;
  sell_date: string | null;
  buyer_name: string | null;
  buyer_tax_no: string | null;
  currency: string | null;
  total_net: string | null;
  total_gross: string | null;
  paid_amount: string | null;
  is_correction: boolean;
  corrected_invoice_fakturownia_id: number | null;
  is_cancelled: boolean;
  is_deleted_upstream: boolean;
  last_synced_at: string | null;
  open_issue_count: number;
  position_count: number;
  positions?: InvoicePosition[];
  raw?: Record<string, unknown> | null;
}

export interface Product {
  id: number;
  fakturownia_product_id: number | null;
  name: string;
  code: string | null;
  ean: string | null;
  sku: string | null;
  unit: string | null;
  kind: string;
  is_stock_controlled: boolean;
  is_active: boolean;
  notes: string | null;
  total_local_stock: string | null;
  fakturownia_quantity: string | null;
  open_issue_count: number;
  aliases?: ProductAlias[];
  bundle_components?: BundleComponent[];
}

export interface ProductAlias {
  id: number;
  product_id: number;
  alias_type: string;
  alias_value: string;
  created_at: string;
}

export interface BundleComponent {
  id: number;
  component_product_id: number;
  quantity: string;
  component_name: string | null;
}

export interface ProductMapping {
  id: number;
  source_name: string | null;
  source_code: string | null;
  source_ean: string | null;
  source_unit: string | null;
  product_id: number | null;
  product_name: string | null;
  match_type: string;
  status: string;
  notes: string | null;
  created_at: string;
  confirmed_at: string | null;
  occurrence_count: number;
}

export interface Warehouse {
  id: number;
  fakturownia_id: number | null;
  name: string;
  kind: string | null;
  description: string | null;
  is_default: boolean;
  product_count: number;
  negative_count: number;
}

export interface StockBalance {
  id: number;
  product_id: number;
  warehouse_id: number;
  quantity: string;
  last_movement_at: string | null;
  last_sale_at: string | null;
  recalculated_at: string | null;
  product_name: string | null;
  product_code: string | null;
  product_unit: string | null;
  warehouse_name: string | null;
  fakturownia_quantity: string | null;
  difference: string | null;
}

export interface StockLedgerEntry {
  id: number;
  product_id: number;
  warehouse_id: number;
  movement_type: string;
  quantity_change: string;
  balance_before: string;
  balance_after: string;
  occurred_at: string;
  sequence: number;
  source_invoice_id: number | null;
  source_invoice_position_id: number | null;
  source_adjustment_id: number | null;
  description: string | null;
  product_name: string | null;
  warehouse_name: string | null;
  invoice_number: string | null;
}

export interface OpeningBalance {
  id: number;
  product_id: number;
  warehouse_id: number;
  quantity: string;
  as_of_date: string;
  note: string | null;
  created_at: string;
  product_name: string | null;
  warehouse_name: string | null;
}

export interface StockAdjustment {
  id: number;
  product_id: number;
  warehouse_id: number;
  quantity_change: string;
  description: string;
  occurred_at: string;
  is_reversal: boolean;
  reverses_adjustment_id: number | null;
  created_at: string;
  product_name: string | null;
  warehouse_name: string | null;
}

export interface ValidationRun {
  id: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  invoices_checked: number;
  positions_checked: number;
  issues_created: number;
  issues_auto_resolved: number;
  message: string | null;
}

export interface IssueComment {
  id: number;
  issue_id: number;
  user_email: string | null;
  body: string;
  created_at: string;
}

export interface ValidationIssue {
  id: number;
  validation_run_id: number | null;
  issue_type: string;
  status: string;
  severity: string;
  invoice_id: number | null;
  invoice_position_id: number | null;
  product_id: number | null;
  warehouse_id: number | null;
  quantity: string | null;
  stock_before: string | null;
  stock_after: string | null;
  technical_description: string | null;
  business_description: string | null;
  recommended_action: string | null;
  created_at: string;
  resolved_at: string | null;
  invoice_number: string | null;
  product_name: string | null;
  warehouse_name: string | null;
  comments: IssueComment[];
}

export interface AuditLogEntry {
  id: number;
  user_email: string | null;
  action: string;
  object_type: string | null;
  object_id: string | null;
  description: string | null;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

export interface FakturowniaClient {
  id: number;
  fakturownia_id: number;
  name: string | null;
  tax_no: string | null;
  email: string | null;
  phone: string | null;
  city: string | null;
  street: string | null;
  post_code: string | null;
  country: string | null;
}

export interface Dashboard {
  last_sync: SyncRun | null;
  last_validation: ValidationRun | null;
  invoice_count: number;
  position_count: number;
  product_count: number;
  client_count: number;
  warehouse_count: number;
  error_count: number;
  warning_count: number;
  needs_mapping_count: number;
  needs_opening_balance_count: number;
  unmapped_position_count: number;
  negative_stock_count: number;
  invoices_needing_attention: {
    id: number;
    number: string;
    issue_date: string | null;
    buyer_name: string | null;
    open_issues: number;
  }[];
  issue_type_breakdown: { issue_type: string; count: number }[];
}

export interface ReportResult {
  report: string;
  title: string;
  headers: string[];
  rows: (string | number | null)[][];
  row_count: number;
}

export interface AppSettingsResponse {
  fakturownia: {
    domain: string | null;
    base_url: string | null;
    token_configured: boolean;
  };
  settings: {
    key: string;
    value: unknown;
    description: string | null;
    is_default?: boolean;
  }[];
}
