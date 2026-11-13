"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";

export function Topbar({ name, onRefresh }: { name?: string; onRefresh?: () => void }) {
  const router = useRouter();
  const path = usePathname();

  async function logout() {
    await api("/api/admin/logout", { method: "POST" }).catch(() => {});
    router.replace("/login");
  }

  return (
    <header className="topbar">
      <nav aria-label="Admin">
        <strong style={{ marginRight: 12 }}>AllJobs Ethiopia Admin</strong>
        <Link href="/" aria-current={path === "/" ? "page" : undefined}>Dashboard</Link>
        <Link href="/users" aria-current={path.startsWith("/users") ? "page" : undefined}>Users</Link>
      </nav>
      <div className="right">
        {name && <span className="who">{name}</span>}
        {onRefresh && <button className="ghost" onClick={onRefresh}>Refresh</button>}
        <button className="ghost" onClick={logout}>Sign out</button>
      </div>
    </header>
  );
}
