import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../lib/auth";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Błąd logowania");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <h1>WMS Kontrola — panel ERP</h1>
        <p>Lokalny system kontroli sprzedaży Fakturowni (tryb tylko-do-odczytu wobec Fakturowni)</p>
        <div className="form-field">
          <label>E-mail</label>
          <input
            type="email" required autoFocus value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="form-field">
          <label>Hasło</label>
          <input
            type="password" required value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error && <div className="form-error">{error}</div>}
        <button className="btn btn--primary" type="submit" disabled={busy}>
          {busy ? "Logowanie…" : "Zaloguj się"}
        </button>
      </form>
    </div>
  );
}
