"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, JobsPage, Status } from "@/lib/api";
import { useAuth } from "./AuthProvider";
import { JobCard } from "./JobCard";

type Section = "this_week" | "past" | "linkedin";

const LINKEDIN = "linkedin";

const PAGE_SIZE = 50;
const BUSY_POLL_MS = 4000;
const IDLE_POLL_MS = 30000;

const TABS: { id: Section; label: string; caption: string; empty: string }[] = [
  {
    id: "this_week",
    label: "This Week",
    caption: "Jobs selected for you in the last 7 days.",
    empty: "Nothing new yet. New jobs are collected and checked every day, so your list builds up as the week goes on.",
  },
  {
    id: "past",
    label: "Past Two Weeks",
    caption: "Jobs move here after a week and are removed after 21 days.",
    empty: "Jobs move here after a week in This Week.",
  },
  {
    id: "linkedin",
    label: "LinkedIn Jobs",
    caption: "Jobs selected for you from LinkedIn. They stay here for 2 weeks.",
    empty: "No LinkedIn jobs yet. They are collected and checked every day, just like the other lists.",
  },
];

function updatedText(value: string): string {
  return new Date(value).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function Feed() {
  const { user, setUser } = useAuth();
  const [section, setSection] = useState<Section>("this_week");
  const [page, setPage] = useState<JobsPage | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("");
  const [pages, setPages] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0);

  const sync = useCallback(async () => {
    const request = ++latest.current;
    const params = new URLSearchParams({ section, limit: String(PAGE_SIZE * pages) });
    if (query) params.set("q", query);
    if (source) params.set("source", source);
    const [jobs, current] = await Promise.all([
      api<JobsPage>(`/api/jobs?${params}`),
      api<Status>("/api/status"),
    ]);
    if (request !== latest.current) return;
    setPage(jobs);
    setStatus(current);
    setError(null);
  }, [section, query, source, pages]);

  const busy = Boolean(status && (status.collecting || status.matching));

  useEffect(() => {
    const tick = () =>
      sync().catch((problem) => {
        if (problem instanceof ApiError && problem.status === 401) setUser(null);
        else setError(problem instanceof Error ? problem.message : "Something went wrong.");
      });
    tick();
    const timer = setInterval(tick, busy ? BUSY_POLL_MS : IDLE_POLL_MS);
    return () => clearInterval(timer);
  }, [busy, sync, setUser]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setPages(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  function choose(next: Section) {
    latest.current++;
    setSection(next);
    setSource("");
    setPage((current) => (current ? { ...current, jobs: [], total: 0 } : current));
    setPages(1);
  }

  const counts: Record<Section, number> = {
    this_week: page?.this_week_count ?? 0,
    past: page?.past_count ?? 0,
    linkedin: page?.linkedin_count ?? 0,
  };
  const tab = TABS.find((t) => t.id === section)!;
  const failed = status?.sources.filter((s) => s.failed) ?? [];
  const hasDescription = Boolean(user?.job_description);
  const filtering = Boolean(query || source);
  // LinkedIn has its own menu, so the site filter only covers the other sites' lists.
  const sites = status?.sources.filter((s) => s.name !== LINKEDIN) ?? [];

  return (
    <main className="page">
      <div role="tablist" aria-label="Job lists" className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={section === t.id}
            aria-controls="job-list"
            className={section === t.id ? "tab tab-active" : "tab"}
            onClick={() => choose(t.id)}
          >
            {t.label}
            {page && <span className="tab-count">{counts[t.id].toLocaleString()}</span>}
          </button>
        ))}
      </div>

      <section id="job-list" role="tabpanel" aria-labelledby={`tab-${section}`}>
        <div className="toolbar">
          <p className="caption">{tab.caption}</p>
          <div className="filters">
            <input
              type="search"
              aria-label="Search by title or company"
              placeholder="Search title or company"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            {section !== "linkedin" && sites.length > 1 && (
            <select
              aria-label="Filter by site"
              value={source}
              onChange={(event) => {
                setSource(event.target.value);
                setPages(1);
              }}
            >
              <option value="">All sites</option>
              {sites.map((s) => (
                <option key={s.name} value={s.name}>{s.label}</option>
              ))}
            </select>
            )}
          </div>
        </div>

        {error && <p className="notice notice-error" role="alert">{error}</p>}
        {failed.map((s) => (
          <p className="notice notice-error" key={s.name}>
            Couldn&apos;t collect today&apos;s jobs from {s.label}. It will try again at the next daily run.
          </p>
        ))}
        {hasDescription && status?.matching && (
          <p className="notice" role="status"><span className="pulse" />Finding jobs that suit you…</p>
        )}
        {hasDescription && !status?.matching && status?.collecting && (
          <p className="notice" role="status"><span className="pulse" />Collecting today&apos;s jobs…</p>
        )}

        {!hasDescription ? (
          <div className="empty">
            <h2>Tell us what you&apos;re looking for</h2>
            <p>Describe the kind of job you want in your profile, and jobs that suit you will start appearing here.</p>
            <Link href="/profile" className="button button-primary">Add my job description</Link>
          </div>
        ) : page === null ? (
          <p className="loading">Loading jobs…</p>
        ) : page.jobs.length > 0 ? (
          <>
            <ul className="jobs">
              {page.jobs.map((job) => <JobCard key={job.id} job={job} />)}
            </ul>
            {page.jobs.length < page.total && (
              <button type="button" className="button button-secondary show-more" onClick={() => setPages(pages + 1)}>
                Show more
              </button>
            )}
          </>
        ) : !busy ? (
          <div className="empty">
            <p>{filtering ? "No jobs match your search." : tab.empty}</p>
          </div>
        ) : null}
      </section>

      {status?.last_updated && (
        <footer className="page-footer">Last updated {updatedText(status.last_updated)}. Checked once a day.</footer>
      )}
    </main>
  );
}
