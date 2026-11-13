import { Job } from "@/lib/api";

function shortDate(value: string): string {
  return new Date(value).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function daysLeft(deadline: string): number {
  return Math.ceil((new Date(deadline).getTime() - Date.now()) / 86_400_000);
}

function deadlineText(job: Job): { text: string; urgent: boolean } | null {
  if (!job.deadline) return null;
  if (job.is_closed) return { text: `Deadline passed ${shortDate(job.deadline)}`, urgent: false };
  const left = daysLeft(job.deadline);
  if (left <= 1) return { text: "Closes today", urgent: true };
  if (left <= 3) return { text: `Closes in ${left} days`, urgent: true };
  return { text: `Closes ${shortDate(job.deadline)}`, urgent: false };
}

export function JobCard({ job }: { job: Job }) {
  const facts = [job.location, job.work_mode, job.job_type, job.experience_level, job.compensation].filter(Boolean);
  const deadline = deadlineText(job);
  return (
    <li className={job.is_closed ? "job job-closed" : "job"}>
      <div className="job-main">
        <div className="job-heading">
          <div>
            <h2>{job.title}</h2>
            {job.company && <p className="company">{job.company}</p>}
          </div>
          <span className={job.score >= 80 ? "score score-strong" : "score"} title="How well this job fits your description, out of 100">
            {job.score}<span className="visually-hidden"> out of 100 fit</span>
          </span>
        </div>
        {facts.length > 0 && <p className="facts">{facts.join(" · ")}</p>}
        {job.reason && <p className="reason">{job.reason}</p>}
        {job.description && (
          <details>
            <summary>Job description</summary>
            <p className="description">{job.description}</p>
          </details>
        )}
      </div>
      <div className="job-footer">
        <a
          className={job.is_closed ? "button button-secondary" : "button button-primary"}
          href={job.apply_url}
          target="_blank"
          rel="noopener noreferrer"
        >
          {job.is_closed ? `View on ${job.source_label}` : `Apply on ${job.source_label}`} <span aria-hidden="true">↗</span>
        </a>
        {deadline && (
          <span className={deadline.urgent ? "deadline deadline-urgent" : job.is_closed ? "deadline deadline-closed" : "deadline"}>
            {deadline.text}
          </span>
        )}
        <span className="added">Added {shortDate(job.selected_at)}</span>
      </div>
    </li>
  );
}
