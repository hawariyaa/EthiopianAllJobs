"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Fragment, useEffect, useState } from "react";
import { BarChart } from "@/components/BarChart";
import { Person } from "@/components/Person";
import { Topbar } from "@/components/Topbar";
import { api, ApiError, type UserDetail } from "@/lib/api";
import { num, usd, when } from "@/lib/format";

function Card({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="card">
      <p className="label">{label}</p>
      <p className="value">{value}</p>
      {sub && <p className="sub">{sub}</p>}
    </div>
  );
}

export default function UserPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const [d, setD] = useState<UserDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stale = false;
    api<UserDetail>(`/api/admin/users/${id}`)
      .then((x) => !stale && setD(x))
      .catch((e) => {
        if (stale) return;
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
        else setError(e instanceof Error ? e.message : "Something went wrong.");
      });
    return () => {
      stale = true;
    };
  }, [id, router]);

  if (!d) {
    return (
      <>
        <Topbar />
        <main className="page">{error ? <p className="error" role="alert">{error}</p> : <p className="muted">Loading…</p>}</main>
      </>
    );
  }

  const { user, matches, ai, selected_jobs } = d;
  return (
    <>
      <Topbar />
      <main className="page">
        <Link className="back" href="/users">← All users</Link>

        <div className="profile">
          <Person id={user.id} name={user.name} has_avatar={user.has_avatar} big />
          <div>
            <h1>{user.name} {user.is_admin && <span className="badge">admin</span>}</h1>
            <p className="muted">{user.email}</p>
          </div>
        </div>

        <section>
          <h2>AI usage</h2>
          <div className="cards">
            <Card label="AI requests sent" value={num(ai.calls)} sub={`${num(ai.calls_7d)} in the last 7 days`} />
            <Card label="Tokens used" value={num(ai.prompt_tokens + ai.completion_tokens)} sub={`${num(ai.prompt_tokens)} in · ${num(ai.completion_tokens)} out`} />
            <Card label="Cost" value={usd(ai.cost)} sub="as reported by OpenRouter" />
            <Card label="Failed requests" value={num(ai.failed)} sub={`${num(ai.attempts)} attempts in total`} />
          </div>
          <p className="muted" style={{ marginTop: 8 }}>
            {ai.tracking_since ? `Counted since ${when(ai.tracking_since)}.` : "No AI requests have been logged for this user yet."} Usage from before logging was added isn&apos;t included.
          </p>
        </section>

        <section>
          <div className="charts">
            <BarChart title="AI requests per day" points={ai.per_day} />
            <div className="card">
              <p className="label">Requests by site group</p>
              <p className="sub" style={{ marginBottom: 8 }}>One request per group per day</p>
              {ai.by_group.length === 0 ? (
                <p className="muted">None yet.</p>
              ) : (
                <dl className="facts">
                  {ai.by_group.map((g) => (
                    <Fragment key={g.group}><dt>{g.label}</dt><dd>{num(g.calls)}</dd></Fragment>
                  ))}
                </dl>
              )}
            </div>
          </div>
        </section>

        <section>
          <h2>Jobs</h2>
          <div className="cards">
            <Card label="Jobs checked" value={num(matches.checked)} sub={`${num(matches.not_selected)} not a fit`} />
            <Card label="Selected for them" value={num(matches.selected)} sub={`average score ${matches.average_score}`} />
            <Card label="This Week" value={num(matches.this_week)} />
            <Card label="Past Two Weeks" value={num(matches.past_two_weeks)} />
          </div>
          <p className="muted" style={{ marginTop: 8 }}>Job counts only cover jobs still stored; the app deletes old ones after 21 days.</p>
        </section>

        <section>
          <h2>Account</h2>
          <div className="card">
            <dl className="facts">
              <dt>User ID</dt><dd>{user.id}</dd>
              <dt>Email</dt><dd>{user.email}</dd>
              <dt>Joined</dt><dd>{when(user.created_at)}</dd>
              <dt>Signed in now</dt><dd>{user.active_sessions > 0 ? `yes, ${user.active_sessions} live session${user.active_sessions > 1 ? "s" : ""}` : "no live session"}</dd>
              <dt>Profile picture</dt><dd>{user.has_avatar ? `yes, updated ${when(user.avatar_updated_at)}` : "none"}</dd>
              <dt>Wishes version</dt><dd>{user.description_version} <span className="muted">(goes up each time they edit their wishes)</span></dd>
              <dt>Checking jobs from</dt><dd>{when(user.matching_from)}</dd>
            </dl>
          </div>
        </section>

        <section>
          <h2>What they&apos;re looking for</h2>
          <div className="card">
            {user.job_description.trim() ? <p className="wishes">{user.job_description}</p> : <p className="muted">They haven&apos;t written anything yet.</p>}
          </div>
        </section>

        <section>
          <h2>Latest AI requests</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>When</th><th>Site group</th><th>Model</th><th className="num">Tokens</th><th className="num">Cost</th><th>Result</th></tr>
              </thead>
              <tbody>
                {ai.recent.map((c, i) => (
                  <tr key={i}>
                    <td>{when(c.created_at)}</td>
                    <td>{c.group_label}</td>
                    <td>{c.model}</td>
                    <td className="num">{num(c.tokens)}</td>
                    <td className="num">{c.cost == null ? "–" : usd(c.cost)}</td>
                    <td>
                      {c.ok ? <span className="badge">ok</span> : <span className="badge bad">failed</span>}
                      {c.attempts > 1 && <span className="muted"> {c.attempts} attempts</span>}
                      {c.error && <p className="muted">{c.error}</p>}
                    </td>
                  </tr>
                ))}
                {ai.recent.length === 0 && <tr><td colSpan={6} className="muted">Nothing logged yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <h2>Jobs selected for them <span className="muted">· latest {selected_jobs.length}</span></h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Job</th><th>Source</th><th className="num">Score</th><th>Why</th><th>Selected</th></tr>
              </thead>
              <tbody>
                {selected_jobs.map((j) => (
                  <tr key={j.job_id}>
                    <td>
                      <a href={j.url} target="_blank" rel="noopener noreferrer">{j.title}</a>
                      {j.company && <p className="muted">{j.company}</p>}
                    </td>
                    <td>{j.source}</td>
                    <td className="num">{j.score}</td>
                    <td>{j.reason}</td>
                    <td>{when(j.selected_at)}</td>
                  </tr>
                ))}
                {selected_jobs.length === 0 && <tr><td colSpan={5} className="muted">No jobs selected yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </>
  );
}
