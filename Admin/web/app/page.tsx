"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { BarChart } from "@/components/BarChart";
import { Topbar } from "@/components/Topbar";
import { api, ApiError, type Admin, type Stats } from "@/lib/api";
import { when } from "@/lib/format";

function Card({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="card">
      <p className="label">{label}</p>
      <p className="value">{value}</p>
      {sub && <p className="sub">{sub}</p>}
    </div>
  );
}

export default function Dashboard() {
  const router = useRouter();
  const [admin, setAdmin] = useState<Admin | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [me, data] = await Promise.all([api<Admin>("/api/admin/me"), api<Stats>("/api/admin/stats")]);
      setAdmin(me);
      setStats(data);
      setError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else setError(e instanceof Error ? e.message : "Something went wrong.");
    }
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  if (!stats) {
    return <main className="page">{error ? <p className="error" role="alert">{error}</p> : <p className="muted">Loading…</p>}</main>;
  }

  const { users, jobs, matches, crawl, series } = stats;
  return (
    <>
      <Topbar name={admin?.name} onRefresh={load} />
      <main className="page">
        {error && <p className="error" role="alert">{error}</p>}

        <section>
          <h2>Users</h2>
          <div className="cards">
            <Card label="Total users" value={users.total} />
            <Card label="New, last 7 days" value={users.new_7d} sub={`${users.new_30d} in 30 days`} />
            <Card label="Described the jobs they want" value={users.with_description} sub={`of ${users.total}`} />
            <Card label="Signed in right now" value={users.signed_in_now} sub="with a live session" />
          </div>
        </section>

        <section>
          <h2>Jobs and AI matching</h2>
          <div className="cards">
            <Card label="Jobs collected" value={jobs.total} sub={`${jobs.new_7d} new in 7 days`} />
            <Card label="AI checks" value={matches.checked_total} sub={`${matches.checked_7d} in 7 days`} />
            <Card label="Jobs selected for users" value={matches.selected_total} sub={`${matches.selected_7d} in 7 days`} />
            <Card label="Average match score" value={matches.average_score} sub="of selected jobs" />
          </div>
        </section>

        <section>
          <h2>Last 30 days (UTC)</h2>
          <div className="charts">
            <BarChart title="Sign-ups" points={series.signups} />
            <BarChart title="New jobs collected" points={series.new_jobs} />
            <BarChart title="AI checks" points={series.ai_checks} />
            <BarChart title="Jobs selected" points={series.selections} />
          </div>
        </section>

        <section>
          <h2>Sources</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Last run</th>
                  <th>Status</th>
                  <th className="num">Seen / new</th>
                  <th>Last success</th>
                  <th className="num">Jobs stored</th>
                  <th className="num">New, 7 days</th>
                </tr>
              </thead>
              <tbody>
                {crawl.map((c) => {
                  const stored = jobs.by_source.find((s) => s.source === c.source);
                  return (
                    <tr key={c.source}>
                      <td>{c.label}</td>
                      <td>{when(c.last_started_at)}</td>
                      <td>
                        {c.last_started_at === null ? (
                          <span className="muted">no runs yet</span>
                        ) : c.last_error ? (
                          <span className="badge bad" title={c.last_error}>failed</span>
                        ) : (
                          <span className="badge">ok</span>
                        )}
                        {c.failed_runs_7d > 0 && <span className="muted"> {c.failed_runs_7d} failed in 7 days</span>}
                        {c.last_error && <p className="muted">{c.last_error}</p>}
                      </td>
                      <td className="num">{c.last_jobs_seen ?? "–"} / {c.last_jobs_new ?? "–"}</td>
                      <td>{when(c.last_success_at)}</td>
                      <td className="num">{stored?.total ?? 0}</td>
                      <td className="num">{stored?.new_7d ?? 0}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <p className="muted">Updated {when(stats.generated_at)}</p>
      </main>
    </>
  );
}
