import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { formatDate } from "../../lib/format";
import type { UserInfo } from "../../lib/types";
import { ActionToolbar } from "../../components/erp/ActionToolbar";
import { Modal } from "../../components/erp/Modal";
import { StatusBadge } from "../../components/erp/StatusBadge";
import { useToast } from "../../components/erp/Toast";

const ROLE_LABELS: Record<string, string> = {
  admin: "Administrator — pełny dostęp",
  operator: "Operator — operacje lokalne",
  auditor: "Audytor — tylko odczyt",
};

interface UserFormState {
  email: string;
  full_name: string;
  password: string;
  roles: string[];
  is_active: boolean;
}

function UserModal({ user, onClose, onSaved }: {
  user: UserInfo | null; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const [form, setForm] = useState<UserFormState>({
    email: user?.email ?? "",
    full_name: user?.full_name ?? "",
    password: "",
    roles: user?.role_names ?? ["operator"],
    is_active: user?.is_active ?? true,
  });

  const toggleRole = (role: string) => {
    setForm((current) => ({
      ...current,
      roles: current.roles.includes(role)
        ? current.roles.filter((r) => r !== role)
        : [...current.roles, role],
    }));
  };

  const save = async () => {
    try {
      if (user) {
        await api.patch(`/users/${user.id}`, {
          full_name: form.full_name,
          password: form.password || undefined,
          is_active: form.is_active,
          roles: form.roles,
        });
      } else {
        await api.post("/users", {
          email: form.email,
          full_name: form.full_name,
          password: form.password,
          roles: form.roles,
        });
      }
      toast.success("Użytkownik zapisany");
      onSaved();
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Błąd zapisu");
    }
  };

  return (
    <Modal
      title={user ? `Edycja: ${user.email}` : "Nowy użytkownik"}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Anuluj</button>
          <button className="btn btn--primary" onClick={save}>Zapisz</button>
        </>
      }
    >
      <div className="form-grid">
        {!user && (
          <div className="form-field">
            <label>E-mail</label>
            <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </div>
        )}
        <div className="form-field">
          <label>Imię i nazwisko</label>
          <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
        </div>
        <div className="form-field">
          <label>{user ? "Nowe hasło (puste = bez zmian)" : "Hasło (min. 8 znaków)"}</label>
          <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </div>
        {user && (
          <div className="form-field">
            <label>Aktywny</label>
            <select
              value={form.is_active ? "1" : "0"}
              onChange={(e) => setForm({ ...form, is_active: e.target.value === "1" })}
            >
              <option value="1">Tak</option>
              <option value="0">Nie (konto zablokowane)</option>
            </select>
          </div>
        )}
        <div className="form-field form-field--full">
          <label>Role</label>
          {Object.entries(ROLE_LABELS).map(([role, label]) => (
            <label key={role} style={{ fontWeight: 400, display: "flex", gap: 6, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={form.roles.includes(role)}
                onChange={() => toggleRole(role)}
              />
              {label}
            </label>
          ))}
        </div>
      </div>
    </Modal>
  );
}

export function UsersPage() {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [modal, setModal] = useState<{ open: boolean; user: UserInfo | null }>({ open: false, user: null });

  const load = useCallback(() => {
    api.get<UserInfo[]>("/users").then(setUsers).catch(() => undefined);
  }, []);

  useEffect(load, [load]);

  return (
    <div>
      <ActionToolbar title="Użytkownicy i role">
        <button className="btn btn--primary" onClick={() => setModal({ open: true, user: null })}>
          + Dodaj użytkownika
        </button>
      </ActionToolbar>
      <div className="datagrid-container">
        <table className="datagrid">
          <thead>
            <tr><th>#</th><th>E-mail</th><th>Imię i nazwisko</th><th>Role</th><th>Aktywny</th><th>Utworzono</th><th></th></tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id}>
                <td>{user.id}</td>
                <td>{user.email}</td>
                <td>{user.full_name || "—"}</td>
                <td>{user.role_names.map((role) => (
                  <span key={role} className="badge badge--info" style={{ marginRight: 4 }}>{role}</span>
                ))}</td>
                <td><StatusBadge value={user.is_active ? "OK" : "ERROR"} /></td>
                <td>{formatDate(user.created_at)}</td>
                <td>
                  <button className="btn btn--small" onClick={() => setModal({ open: true, user })}>Edytuj</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel" style={{ marginTop: 8 }}>
        <div className="panel__header">Role systemowe</div>
        <div className="panel__body">
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            <li><b>admin</b> — użytkownicy, ustawienia, wszystkie operacje lokalne</li>
            <li><b>operator</b> — synchronizacja, mapowania, korekty magazynowe, walidacje, komentarze</li>
            <li><b>auditor</b> — tylko odczyt danych, raportów i audytu</li>
          </ul>
        </div>
      </div>
      {modal.open && (
        <UserModal user={modal.user} onClose={() => setModal({ open: false, user: null })} onSaved={load} />
      )}
    </div>
  );
}
