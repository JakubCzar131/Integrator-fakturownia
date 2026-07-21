import {
  createContext, useCallback, useContext, useEffect, useState, type ReactNode,
} from "react";
import { api, getToken, setToken } from "./api";
import type { UserInfo } from "./types";

interface AuthState {
  user: UserInfo | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  hasRole: (...roles: string[]) => boolean;
  canWrite: boolean;
  isAdmin: boolean;
}

const AuthContext = createContext<AuthState>({
  user: null, loading: true,
  login: async () => undefined, logout: () => undefined,
  hasRole: () => false, canWrite: false, isAdmin: false,
});

export function useAuth(): AuthState {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api.get<UserInfo>("/auth/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    await api.login(email, password);
    const me = await api.get<UserInfo>("/auth/me");
    setUser(me);
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    window.location.href = "/login";
  }, []);

  const hasRole = useCallback(
    (...roles: string[]) => !!user && roles.some((r) => user.role_names.includes(r)),
    [user],
  );

  return (
    <AuthContext.Provider
      value={{
        user, loading, login, logout, hasRole,
        canWrite: hasRole("admin", "operator"),
        isAdmin: hasRole("admin"),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
