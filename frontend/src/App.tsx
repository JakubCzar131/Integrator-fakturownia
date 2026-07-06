import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { Sidebar } from "./components/erp/Sidebar";
import { Topbar } from "./components/erp/Topbar";
import { ToastProvider } from "./components/erp/Toast";
import { AuthProvider, useAuth } from "./lib/auth";
import { AuditPage } from "./modules/audit/AuditPage";
import { LoginPage } from "./modules/auth/LoginPage";
import { ClientsPage } from "./modules/clients/ClientsPage";
import { DashboardPage } from "./modules/dashboard/DashboardPage";
import { InvoiceDetailPage } from "./modules/invoices/InvoiceDetailPage";
import { InvoicePositionsPage } from "./modules/invoices/InvoicePositionsPage";
import { InvoicesPage } from "./modules/invoices/InvoicesPage";
import { MappingsPage } from "./modules/products/MappingsPage";
import { ProductDetailPage } from "./modules/products/ProductDetailPage";
import { ProductsPage } from "./modules/products/ProductsPage";
import { ReportsPage } from "./modules/reports/ReportsPage";
import { SettingsPage } from "./modules/settings/SettingsPage";
import { StockBalancesPage } from "./modules/stock/StockBalancesPage";
import { StockLedgerPage } from "./modules/stock/StockLedgerPage";
import { WarehousesPage } from "./modules/stock/WarehousesPage";
import { SyncPage } from "./modules/sync/SyncPage";
import { UsersPage } from "./modules/users/UsersPage";
import { ValidationPage } from "./modules/validation/ValidationPage";

function ProtectedLayout() {
  const { user, loading } = useAuth();
  if (loading) return <div style={{ padding: 40 }} className="text-muted">Ładowanie…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return (
    <div className="app-shell">
      <Topbar />
      <div className="app-body">
        <Sidebar />
        <main className="app-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<ProtectedLayout />}>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/invoices" element={<InvoicesPage />} />
              <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
              <Route path="/invoice-positions" element={<InvoicePositionsPage />} />
              <Route path="/clients" element={<ClientsPage />} />
              <Route path="/products" element={<ProductsPage />} />
              <Route path="/products/:id" element={<ProductDetailPage />} />
              <Route path="/mappings" element={<MappingsPage />} />
              <Route path="/warehouses" element={<WarehousesPage />} />
              <Route path="/stock-balances" element={<StockBalancesPage />} />
              <Route path="/stock-ledger" element={<StockLedgerPage />} />
              <Route path="/validation" element={<ValidationPage />} />
              <Route path="/reports" element={<ReportsPage />} />
              <Route path="/sync" element={<SyncPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/users" element={<UsersPage />} />
              <Route path="/audit" element={<AuditPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  );
}
