import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useToast } from "./Toast";
import { SyncStatusWidget } from "./SyncStatusWidget";

export function Topbar() {
  const { user, logout, canWrite } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [validating, setValidating] = useState(false);

  const runSync = async () => {
    try {
      await api.post("/sync/incremental");
      toast.info("Synchronizacja przyrostowa uruchomiona w tle");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd synchronizacji");
    }
  };

  const runValidation = async () => {
    setValidating(true);
    try {
      const run = await api.post<{ message: string | null }>("/validation/run");
      toast.success(run.message ?? "Walidacja zakończona");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd walidacji");
    } finally {
      setValidating(false);
    }
  };

  const handleSearch = (event: React.FormEvent) => {
    event.preventDefault();
    if (search.trim()) {
      navigate(`/invoices?search=${encodeURIComponent(search.trim())}`);
    }
  };

  return (
    <header className="topbar">
      <span className="topbar__brand">
        WMS Kontrola<small>panel ERP dla Fakturowni · tylko odczyt</small>
      </span>
      <SyncStatusWidget />
      <span className="topbar__spacer" />
      <form className="topbar__search" onSubmit={handleSearch}>
        <input
          placeholder="Szukaj faktury / klienta…  (Enter)"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </form>
      {canWrite && (
        <>
          <button className="btn btn--small" onClick={runSync}>⟳ Synchronizuj</button>
          <button className="btn btn--small btn--primary" onClick={runValidation} disabled={validating}>
            {validating ? <span className="spinner" /> : "✓"} Waliduj
          </button>
        </>
      )}
      <span className="topbar__user">
        <b>{user?.full_name || user?.email}</b> ({user?.role_names.join(", ")})
      </span>
      <button className="btn btn--small" onClick={logout}>Wyloguj</button>
    </header>
  );
}
