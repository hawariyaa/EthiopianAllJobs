"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { sendJson, User } from "@/lib/api";

export default function RegisterPage() {
  const { user, setUser } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const justRegistered = useRef(false);

  useEffect(() => {
    if (user) router.replace(justRegistered.current ? "/profile?welcome" : "/");
  }, [user, router]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await sendJson<User>("/api/auth/register", "POST", { name, email, password });
      justRegistered.current = true;
      setUser(created);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Couldn't create your account.");
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <form className="panel auth-form" onSubmit={submit}>
        <h1>Create your account</h1>
        {error && <p className="notice notice-error" role="alert">{error}</p>}
        <label htmlFor="name">Name</label>
        <input id="name" autoComplete="name" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
        <label htmlFor="email">Email</label>
        <input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <label htmlFor="password">Password</label>
        <input id="password" type="password" autoComplete="new-password" required minLength={8} maxLength={128} aria-describedby="password-hint" value={password} onChange={(e) => setPassword(e.target.value)} />
        <p className="field-hint" id="password-hint">At least 8 characters.</p>
        <button type="submit" className="button button-primary button-block" disabled={busy}>
          {busy ? "Creating…" : "Create account"}
        </button>
        <p className="auth-switch">Already have an account? <Link href="/login">Log in</Link></p>
      </form>
    </main>
  );
}
