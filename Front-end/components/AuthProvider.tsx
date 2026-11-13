"use client";

import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError, User } from "@/lib/api";

type Auth = {
  user: User | null;
  loading: boolean;
  offline: boolean;
  setUser: (user: User | null) => void;
  logout: () => Promise<void>;
};

const AuthContext = createContext<Auth | null>(null);
const RETRY_MS = 10000;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;

    async function load() {
      try {
        const me = await api<User>("/api/auth/me");
        if (stopped) return;
        setUser(me);
        setOffline(false);
        setLoading(false);
      } catch (error) {
        if (stopped) return;
        if (error instanceof ApiError && error.status === 401) {
          setUser(null);
          setOffline(false);
          setLoading(false);
        } else {
          setOffline(true);
          timer = setTimeout(load, RETRY_MS);
        }
      }
    }

    load();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, []);

  const logout = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" });
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, offline, setUser, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth must be used inside AuthProvider");
  return auth;
}
