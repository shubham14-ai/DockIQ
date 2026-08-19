import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiGet, apiPost, ApiError, clearToken, getToken, onUnauthorized, setToken } from "../api/client";

export interface AuthUser {
  username: string;
  role: string;
  tenant_id?: string;
  kind?: string;
}

interface LoginResponse {
  access_token: string;
  token_type: string;
  role: string;
  tenant_id?: string;
  username: string;
}

interface AuthContextValue {
  token: string | null;
  user: AuthUser | null;
  loading: boolean;
  error: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

// Bumped whenever the client wants to force a re-check of auth state (e.g.
// after a 401 clears the token out from under the app).
let listeners: Array<() => void> = [];
export function notifyAuthChanged() {
  listeners.forEach((fn) => fn());
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState<boolean>(() => !!getToken());
  const [error, setError] = useState<string | null>(null);

  const hydrate = useCallback(async () => {
    setLoading(true);
    try {
      const me = await apiGet<AuthUser>("/auth/me");
      setUser(me);
    } catch {
      clearToken();
      setTokenState(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const cb = () => {
      const t = getToken();
      setTokenState(t);
      if (!t) setUser(null);
    };
    listeners.push(cb);
    return () => {
      listeners = listeners.filter((l) => l !== cb);
    };
  }, []);

  // Global 401 handler from the fetch wrapper: drop stale auth state so the
  // app falls back to the login screen.
  useEffect(() => {
    onUnauthorized(() => {
      setTokenState(null);
      setUser(null);
    });
  }, []);

  useEffect(() => {
    if (token) {
      hydrate();
    } else {
      setUser(null);
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const login = useCallback(async (username: string, password: string) => {
    setError(null);
    try {
      const res = await apiPost<LoginResponse>("/auth/login", { username, password });
      setToken(res.access_token);
      setTokenState(res.access_token);
      setUser({ username: res.username, role: res.role, tenant_id: res.tenant_id });
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Login failed";
      setError(msg);
      throw err;
    }
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setTokenState(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ token, user, loading, error, login, logout }),
    [token, user, loading, error, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
