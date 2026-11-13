export type Admin = { id: number; email: string; name: string };

export type Point = { date: string; count: number };

export type Stats = {
  generated_at: string;
  users: { total: number; with_description: number; new_7d: number; new_30d: number; signed_in_now: number };
  jobs: { total: number; new_7d: number; by_source: { source: string; label: string; total: number; new_7d: number }[] };
  matches: { checked_total: number; checked_7d: number; selected_total: number; selected_7d: number; average_score: number };
  crawl: {
    source: string;
    label: string;
    last_started_at: string | null;
    last_jobs_seen: number | null;
    last_jobs_new: number | null;
    last_error: string | null;
    last_success_at: string | null;
    failed_runs_7d: number;
  }[];
  series: { signups: Point[]; new_jobs: Point[]; ai_checks: Point[]; selections: Point[] };
};

export type UserRow = {
  id: number;
  name: string;
  email: string;
  is_admin: boolean;
  has_description: boolean;
  has_avatar: boolean;
  created_at: string;
  ai_calls: number;
  ai_tokens: number;
  ai_cost: number;
  jobs_checked: number;
  jobs_selected: number;
};

export type UserList = { total: number; users: UserRow[] };

export type UserDetail = {
  user: {
    id: number;
    name: string;
    email: string;
    is_admin: boolean;
    created_at: string;
    job_description: string;
    description_version: number;
    matching_from: string;
    has_avatar: boolean;
    avatar_updated_at: string | null;
    active_sessions: number;
  };
  matches: {
    checked: number;
    selected: number;
    not_selected: number;
    this_week: number;
    past_two_weeks: number;
    average_score: number;
  };
  ai: {
    calls: number;
    calls_7d: number;
    failed: number;
    by_group: { group: string; label: string; calls: number }[];
    attempts: number;
    prompt_tokens: number;
    completion_tokens: number;
    cost: number;
    tracking_since: string | null;
    per_day: Point[];
    recent: {
      created_at: string;
      kind: string;
      group_label: string;
      model: string;
      attempts: number;
      tokens: number;
      cost: number | null;
      ok: boolean;
      error: string | null;
    }[];
  };
  selected_jobs: {
    job_id: number;
    title: string;
    company: string | null;
    source: string;
    url: string;
    score: number;
    reason: string;
    selected_at: string;
  }[];
};

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export async function api<T = void>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("Can't reach the admin server. Is it running?", 0);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : "Something went wrong. Please try again.";
    throw new ApiError(response.status >= 500 ? "The admin server isn't responding right now." : detail, response.status);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
