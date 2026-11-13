export type User = {
  id: number;
  email: string;
  name: string;
  job_description: string;
  avatar_updated_at: string | null;
};

export type Job = {
  id: number;
  title: string;
  company: string | null;
  location: string | null;
  description: string;
  apply_url: string;
  source: string;
  source_label: string;
  job_type: string | null;
  work_mode: string | null;
  experience_level: string | null;
  compensation: string | null;
  published_at: string | null;
  deadline: string | null;
  is_closed: boolean;
  selected_at: string;
  score: number;
  reason: string;
};

export type JobsPage = {
  total: number;
  this_week_count: number;
  past_count: number;
  linkedin_count: number;
  jobs: Job[];
};

export type Status = {
  collecting: boolean;
  matching: boolean;
  last_updated: string | null;
  sources: { name: string; label: string; failed: boolean }[];
};

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

function errorMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.loc) {
    const field = detail[0].loc[detail[0].loc.length - 1];
    if (field === "email") return "Please enter a valid email address.";
    if (String(field).includes("password")) return "Passwords need at least 8 characters.";
    if (field === "name") return "Please enter your name.";
  }
  return "Something went wrong. Please try again.";
}

export async function api<T = void>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("Can't reach the server. Please check your connection.", 0);
  }
  if (response.status >= 500) throw new ApiError("The server isn't responding right now.", response.status);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(errorMessage(body?.detail), response.status);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export function sendJson<T = void>(path: string, method: string, body: unknown): Promise<T> {
  return api<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}
