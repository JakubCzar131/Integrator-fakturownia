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
    source: string;
    label: string | null;
  };
  skyshop: {
    base_url: string | null;
    key_configured: boolean;
    source: string;
    label: string | null;
  };
  settings: {
    key: string;
    value: unknown;
    description: string | null;
    is_default?: boolean;
  }[];
}

// ------------------------- integration accounts ------------------------- //

export interface IntegrationAccount {
  id: number;
  provider: string;
  label: string;
  config: Record<string, unknown>;
  secret_configured: boolean;
  secret_hint: string | null;
  is_active: boolean;
  verified_at: string | null;
  verified_status: string;
  verified_error: string | null;
  created_at: string;
  updated_at: string | null;
  is_effective: boolean;
}

export interface EffectiveIntegration {
  provider: string;
  source: string;
  is_configured: boolean;
  label: string | null;
  account_id: number | null;
  target: string | null;
  details: Record<string, unknown>;
}

export interface ConnectionTestResult {
  ok: boolean;
  message: string;
  detail: Record<string, unknown> | null;
}

// ---------------------------- reconciliation ---------------------------- //

export interface ReconciliationRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  trigger: string;
  sync_run_id: number | null;
  line_count: number;
  discrepancy_count: number;
  tolerance: string | null;
  stats: Record<string, unknown> | null;
}

export interface ReconciliationLine {
  id: number;
  run_id: number;
  product_id: number;
  warehouse_id: number | null;
  fakturownia_stock: string | null;
  inbound_pz: string;
  inbound_pw: string;
  outbound_documents: string;
  sold_invoices: string;
  corrections: string;
  opening_balance: string | null;
  local_ledger_stock: string | null;
  computed_stock: string;
  difference: string | null;
  status: string;
  computed_at: string;
  product_name: string | null;
  product_code: string | null;
  product_unit: string | null;
  warehouse_name: string | null;
}

// -------------------------- warehouse documents ------------------------- //

export interface WarehouseDocumentPosition {
  id: number;
  document_id: number;
  document_kind: string | null;
  fakturownia_id: number | null;
  product_fakturownia_id: number | null;
  mapped_product_id: number | null;
  mapping_status: string | null;
  mapping_match_type: string | null;
  name: string | null;
  code: string | null;
  quantity: string | null;
  quantity_unit: string | null;
  purchase_price_net: string | null;
  issue_date: string | null;
  warehouse_fakturownia_id: number | null;
  product_name: string | null;
  document_number: string | null;
}

export interface WarehouseDocument {
  id: number;
  fakturownia_id: number;
  kind: string | null;
  number: string | null;
  warehouse_fakturownia_id: number | null;
  issue_date: string | null;
  invoice_fakturownia_id: number | null;
  description: string | null;
  is_deleted_upstream: boolean;
  last_synced_at: string | null;
  warehouse_name: string | null;
  position_count: number;
  total_quantity: string | null;
  unmapped_position_count: number;
  positions?: WarehouseDocumentPosition[];
  raw?: Record<string, unknown> | null;
}

export interface WarehouseDocumentSummary {
  by_kind: { kind: string; documents: number }[];
  inbound_position_count: number;
  inbound_unmapped_count: number;
  inbound_quantity: string;
}

// -------------------------------- SkyShop ------------------------------- //

export interface SkyShopSummary {
  write_enabled: boolean;
  dry_run: boolean;
  stock_source: string;
  link_status_counts: Record<string, number>;
  job_status_counts: Record<string, number>;
  mirror_product_count: number;
  mirror_synced_at: string | null;
  last_push_at: string | null;
  pending_jobs: number;
  failed_jobs: number;
}

export interface SkyShopLink {
  id: number;
  product_id: number;
  skyshop_id: string | null;
  status: string;
  match_type: string | null;
  candidate_skyshop_ids: string[] | null;
  last_pushed_stock: string | null;
  last_pushed_content_hash: string | null;
  last_pushed_at: string | null;
  last_error: string | null;
  notes: string | null;
  product_name: string | null;
  product_code: string | null;
  product_sku: string | null;
  product_ean: string | null;
  local_stock: string | null;
  shop_stock: string | null;
  shop_name: string | null;
  stock_out_of_sync: boolean;
  content_out_of_sync: boolean;
}

export interface SkyShopProduct {
  id: number;
  skyshop_id: string;
  sku: string | null;
  ean: string | null;
  name: string | null;
  price_gross: string | null;
  quantity: string | null;
  category_skyshop_id: string | null;
  is_active: boolean | null;
  is_deleted_upstream: boolean;
  last_synced_at: string | null;
}

export interface SkyShopCategory {
  id: number;
  skyshop_id: string;
  name: string | null;
  parent_skyshop_id: string | null;
  path: string | null;
  mapped_local_category: string | null;
}

export interface SkyShopCategoryMapping {
  id: number;
  local_category: string;
  skyshop_category_id: string;
  skyshop_category_name: string | null;
  updated_at: string | null;
}

export interface ProductContent {
  product_id: number;
  description_html: string | null;
  short_description: string | null;
  images: { url?: string; alt?: string; position?: number }[];
  attributes: Record<string, string>;
  price_gross: string | null;
  vat_rate: string | null;
  local_category: string | null;
  weight: string | null;
  is_publishable: boolean;
  updated_at: string | null;
  content_hash: string | null;
  publication_problems: string[];
}

export interface SyncJob {
  id: number;
  provider: string;
  job_type: string;
  dedupe_key: string | null;
  payload: Record<string, unknown>;
  status: string;
  priority: number;
  attempts: number;
  max_attempts: number;
  next_attempt_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  result: Record<string, unknown> | null;
  last_error: string | null;
  product_id: number | null;
  product_name: string | null;
  created_at: string;
}

export interface MessageResponse {
  message: string;
  detail?: Record<string, unknown> | null;
}
