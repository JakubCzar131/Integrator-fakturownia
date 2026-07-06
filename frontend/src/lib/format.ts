export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return value.slice(0, 10);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pl-PL", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

export function formatQty(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const num = typeof value === "number" ? value : parseFloat(value);
  if (Number.isNaN(num)) return String(value);
  return num.toLocaleString("pl-PL", { maximumFractionDigits: 4 });
}

export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const num = typeof value === "number" ? value : parseFloat(value);
  if (Number.isNaN(num)) return String(value);
  return num.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

export const MOVEMENT_TYPE_LABELS: Record<string, string> = {
  OPENING_BALANCE: "Stan początkowy",
  SALE: "Sprzedaż",
  SALE_CORRECTION: "Korekta sprzedaży",
  MANUAL_ADJUSTMENT: "Korekta ręczna",
  IMPORTED_WAREHOUSE_ACTION: "Import akcji mag.",
};

export const PRODUCT_KIND_LABELS: Record<string, string> = {
  STOCK_ITEM: "Towar magazynowy",
  SERVICE: "Usługa",
  IGNORED: "Ignorowany",
  BUNDLE: "Zestaw/pakiet",
  NEEDS_MAPPING: "Do klasyfikacji",
};

export const ISSUE_TYPE_LABELS: Record<string, string> = {
  PRODUCT_NOT_RECOGNIZED: "Nierozpoznany produkt",
  PRODUCT_ID_MISSING: "Brak product_id",
  NEGATIVE_STOCK: "Stan ujemny",
  INSUFFICIENT_STOCK: "Niewystarczający stan",
  UNIT_MISMATCH: "Niezgodna jednostka",
  DUPLICATE_INVOICE: "Zdublowana faktura",
  CANCELLED_INVOICE_INCLUDED: "Anulowana rozliczona",
  CORRECTION_NOT_HANDLED: "Nieobsłużona korekta",
  SERVICE_INCLUDED_IN_STOCK: "Usługa w magazynie",
  MISSING_OPENING_BALANCE: "Brak stanu początkowego",
  STOCK_DISCREPANCY: "Rozbieżność stanów",
  UNKNOWN_DOCUMENT_TYPE: "Nieznany typ dokumentu",
  UNKNOWN_PRODUCT_TYPE: "Nieznany typ produktu",
  INVALID_QUANTITY: "Nieprawidłowa ilość",
  MAPPING_CONFLICT: "Konflikt mapowania",
  LOCAL_RULE_REQUIRED: "Wymagana reguła lokalna",
  SALE_BEFORE_OPENING_BALANCE: "Sprzedaż przed stanem pocz.",
  INACTIVE_PRODUCT_SOLD: "Produkt nieaktywny",
  DOUBLE_STOCK_SETTLEMENT: "Podwójne rozliczenie",
  UNKNOWN_UNIT: "Nieznana jednostka",
};

export const STATUS_LABELS: Record<string, string> = {
  OK: "OK",
  WARNING: "Ostrzeżenie",
  ERROR: "Błąd",
  NEEDS_MAPPING: "Do zmapowania",
  NEEDS_OPENING_BALANCE: "Brak stanu pocz.",
  IGNORED: "Zignorowany",
  RESOLVED: "Rozwiązany",
  RUNNING: "W toku",
  SUCCESS: "Sukces",
  PARTIAL: "Częściowy",
  FAILED: "Niepowodzenie",
  CONFIRMED: "Zatwierdzone",
  PROPOSED: "Propozycja",
  REJECTED: "Odrzucone",
};
