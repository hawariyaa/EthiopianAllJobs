"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "./AuthProvider";
import { Avatar } from "./Avatar";

export function Header() {
  const { user, loading, offline, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (!menu.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function signOut() {
    setOpen(false);
    try {
      await logout();
    } finally {
      router.push("/");
    }
  }

  return (
    <>
      <header className="site-header">
        <div className="site-header-inner">
          <Link href="/" className="brand">
            <span className="brand-mark" aria-hidden="true">A</span>
            AllJobs Ethiopia
          </Link>
          {!loading && !user && (
            <nav className="header-actions">
              <Link href="/login" className="button button-quiet">Log in</Link>
              <Link href="/register" className="button button-primary">Register</Link>
            </nav>
          )}
          {user && (
            <div className="menu" ref={menu}>
              <button
                type="button"
                className="menu-button"
                aria-expanded={open}
                aria-haspopup="true"
                aria-label="Account menu"
                onClick={() => setOpen(!open)}
              >
                <Avatar user={user} />
                <span className="menu-name">{user.name}</span>
              </button>
              {open && (
                <div className="menu-list">
                  <p className="menu-email">{user.email}</p>
                  <Link href="/" onClick={() => setOpen(false)}>My jobs</Link>
                  <Link href="/profile" onClick={() => setOpen(false)}>Profile</Link>
                  <button type="button" onClick={signOut}>Log out</button>
                </div>
              )}
            </div>
          )}
        </div>
      </header>
      {offline && (
        <p className="banner" role="alert">Can&apos;t reach the server. Trying again…</p>
      )}
    </>
  );
}
