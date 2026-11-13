"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Person } from "@/components/Person";
import { Topbar } from "@/components/Topbar";
import { api, ApiError, type UserList } from "@/lib/api";
import { day, num, usd } from "@/lib/format";

const PAGE = 50;
const SORTS = [
  ["newest", "Newest first"],
  ["oldest", "Oldest first"],
  ["name", "Name"],
  ["ai_calls", "Most AI requests"],
  ["selected", "Most jobs selected"],
] as const;

export default function Users() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("newest");
  const [page, setPage] = useState(0);
  const [data, setData] = useState<UserList | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(q);
      setPage(0);
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const params = new URLSearchParams({ q: search, sort, limit: String(PAGE), offset: String(page * PAGE) });
    let stale = false;
    api<UserList>(`/api/admin/users?${params}`)
      .then((d) => !stale && (setData(d), setError("")))
      .catch((e) => {
        if (stale) return;
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
        else setError(e instanceof Error ? e.message : "Something went wrong.");
      });
    return () => {
      stale = true;
    };
  }, [search, sort, page, router]);

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;
  return (
    <>
      <Topbar />
      <main className="page">
        <div className="toolbar">
          <h2 style={{ margin: 0 }}>Users{data && <span className="muted"> · {num(data.total)}</span>}</h2>
          <div className="toolbar">
            <input type="search" placeholder="Search name or email" aria-label="Search users" value={q} onChange={(e) => setQ(e.target.value)} />
            <select aria-label="Sort" value={sort} onChange={(e) => { setSort(e.target.value); setPage(0); }}>
              {SORTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </div>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        {!data && !error && <p className="muted">Loading…</p>}
        {data && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Joined</th>
                  <th className="num">AI requests</th>
                  <th className="num">Tokens</th>
                  <th className="num">AI cost</th>
                  <th className="num">Jobs checked</th>
                  <th className="num">Selected</th>
                  <th>Wishes</th>
                </tr>
              </thead>
              <tbody>
                {data.users.map((u) => (
                  <tr key={u.id} className="link">
                    <td>
                      <div className="person">
                        <Person id={u.id} name={u.name} has_avatar={u.has_avatar} />
                        <div>
                          <Link className="row-link" href={`/users/${u.id}`}>{u.name}</Link>
                          {u.is_admin && <> <span className="badge">admin</span></>}
                          <p className="muted">{u.email}</p>
                        </div>
                      </div>
                    </td>
                    <td>{day(u.created_at)}</td>
                    <td className="num">{num(u.ai_calls)}</td>
                    <td className="num">{num(u.ai_tokens)}</td>
                    <td className="num">{usd(u.ai_cost)}</td>
                    <td className="num">{num(u.jobs_checked)}</td>
                    <td className="num">{num(u.jobs_selected)}</td>
                    <td>{u.has_description ? <span className="badge">written</span> : <span className="badge bad">empty</span>}</td>
                  </tr>
                ))}
                {data.users.length === 0 && (
                  <tr><td colSpan={8} className="muted">No users match.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
        {pages > 1 && (
          <div className="pager">
            <button className="ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="muted">Page {page + 1} of {pages}</span>
            <button className="ghost" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        )}
        <p className="muted">AI requests, tokens and cost are counted from when request logging was added; earlier use isn&apos;t included.</p>
      </main>
    </>
  );
}
