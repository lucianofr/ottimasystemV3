import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import {
  api,
  clearToken,
  getToken,
  setToken,
  type LoginOut,
  type UserOut,
} from "../../lib/api";

interface AuthState {
  user: UserOut | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const queryClient = useQueryClient();
  const [loading, setLoading] = useState(true);

  // restauração de sessão: token persistido -> GET /api/auth/me (spec §5.1/§8.5)
  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api<UserOut>("/api/auth/me")
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const out = await api<LoginOut>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setToken(out.access_token);
    setUser(out.user);
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    // o QueryClient é singleton: sem isso o próximo operador na mesma estação
    // veria os dados cacheados do anterior (spec §8.5)
    queryClient.clear();
  }, [queryClient]);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth fora de AuthProvider");
  return ctx;
}

/**
 * Único ponto de decisão de permissão na UI: o operador enxerga tudo (ADR-015),
 * só não dispara mutação de engenharia. É ergonomia, não segurança — a fronteira
 * real é o `require_admin` da API, que devolve 403 independentemente da tela.
 */
export function useCanMutate(): boolean {
  return useAuth().user?.role === "admin";
}
