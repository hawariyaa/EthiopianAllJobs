"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { sendJson, User } from "@/lib/api";

export default function LoginPage() {
  const { user, setUser } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (user) router.replace("/");
  }, [user, router]);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).has("password-changed")) {
      setNotice("Your password was changed. Please log in again.");
    }
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setUser(await sendJson<User>("/api/auth/login", "POST", { email, password }));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Couldn't log in.");
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <form className="panel auth-form" onSubmit={submit}>
        <h1>Log in</h1>
        {notice && <p className="notice" role="status">{notice}</p>}
        {error && <p className="notice notice-error" role="alert">{error}</p>}
        <label htmlFor="email">Email</label>
        <input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <label htmlFor="password">Password</label>
        <input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <button type="submit" className="button button-primary button-block" disabled={busy}>
          {busy ? "Logging in…" : "Log in"}
        </button>
        <p className="auth-switch">New here? <Link href="/register">Create an account</Link></p>
      </form>
    </main>
  );
}
