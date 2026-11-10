import type { ReactNode } from "react";
import type { Review, Severity } from "./api";

export function StatusBadge({ status }: { status: Review["status"] }) {
  return (
    <span className={`badge status-${status}`}>
      {status === "running" && <span className="pulse" />}
      {status}
    </span>
  );
}

const VERDICTS: Record<string, string> = {
  approve: "Looks good",
  comment: "Comments",
  request_changes: "Changes suggested",
};

export function VerdictBadge({ verdict }: { verdict: Review["verdict"] }) {
  if (!verdict) return <span className="muted">—</span>;
  return <span className={`verdict verdict-${verdict}`}>{VERDICTS[verdict]}</span>;
}

export function SeverityDot({ severity }: { severity: Severity | string }) {
  return <span className={`dot sev-${severity}`} aria-label={severity} />;
}

export function Card({ title, children, action }: { title?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="card">
      {(title || action) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

/** Horizontal bars for a {label: count} breakdown. */
export function Breakdown({ data, order, colorPrefix }: { data: Record<string, number>; order?: string[]; colorPrefix?: string }) {
  const keys = order ? order.filter((k) => k in data) : Object.keys(data).sort((a, b) => data[b] - data[a]);
  const max = Math.max(1, ...keys.map((k) => data[k]));
  if (keys.length === 0) return <Empty>No data yet</Empty>;
  return (
    <ul className="breakdown">
      {keys.map((k) => (
        <li key={k}>
          <span className="breakdown-label">{k.replace("_", " ")}</span>
          <span className="breakdown-track">
            <span
              className={`breakdown-bar ${colorPrefix ? `${colorPrefix}-${k}` : ""}`}
              style={{ width: `${(data[k] / max) * 100}%` }}
            />
          </span>
          <span className="breakdown-value">{data[k]}</span>
        </li>
      ))}
    </ul>
  );
}

function dayLabel(iso: string, index: number): string {
  const date = new Date(iso + "T00:00:00");
  const day = date.getDate();
  return index === 0 || day === 1 ? date.toLocaleDateString("en", { day: "numeric", month: "short" }) : String(day);
}

/** Paired columns per day: reviews (solid) and issues found (outline). */
export function DailyChart({ days }: { days: { day: string; reviews: number; issues: number }[] }) {
  const max = Math.max(1, ...days.map((d) => Math.max(d.reviews, d.issues)));
  return (
    <div className="daily">
      <div className="daily-legend">
        <span><i className="sw sw-reviews" /> Reviews</span>
        <span><i className="sw sw-issues" /> Issues found</span>
      </div>
      <div className="daily-bars">
        {days.map((d, i) => (
          <div className="daily-col" key={d.day} title={`${d.day}: ${d.reviews} reviews, ${d.issues} issues`}>
            <div className="daily-pair">
              <span className="bar-reviews" style={{ height: `${(d.reviews / max) * 100}%` }} />
              <span className="bar-issues" style={{ height: `${(d.issues / max) * 100}%` }} />
            </div>
            <span className="daily-label">{dayLabel(d.day, i)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="error-box">
      Couldn't reach the API: {message}. Is the backend running on port 8000?
    </div>
  );
}
