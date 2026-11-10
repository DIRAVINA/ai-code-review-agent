import { Link } from "react-router-dom";
import { api } from "../api";
import { Breakdown, Card, DailyChart, Empty, ErrorBox, Stat, StatusBadge, VerdictBadge } from "../components";
import { compact, formatDuration, timeAgo, useAsync } from "../hooks";

export default function Overview() {
  const stats = useAsync(api.stats, []);
  const recent = useAsync(() => api.reviews({ limit: 6 }), [], (d) =>
    d.items.some((r) => r.status === "queued" || r.status === "running"),
  );

  if (stats.error) return <ErrorBox message={stats.error} />;
  const s = stats.data;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <p className="muted">Pull requests reviewed by the agent over the last two weeks.</p>
        </div>
      </div>

      <div className="stats-row">
        <Stat label="Reviews" value={s ? compact(s.total_reviews) : "…"} hint={s ? `${s.by_status.completed ?? 0} completed` : ""} />
        <Stat
          label="Issues found"
          value={s ? compact(s.total_issues) : "…"}
          hint={s ? `${s.by_severity.error ?? 0} errors` : ""}
        />
        <Stat label="Avg review time" value={s ? formatDuration(s.avg_duration_ms && Math.round(s.avg_duration_ms)) : "…"} />
        <Stat label="Tokens used" value={s ? compact(s.total_tokens) : "…"} />
      </div>

      <Card title="Activity">{s ? <DailyChart days={s.per_day} /> : <div className="skeleton tall" />}</Card>

      <div className="grid-3">
        <Card title="By severity">
          {s && <Breakdown data={s.by_severity} order={["error", "warning", "info"]} colorPrefix="sev" />}
        </Card>
        <Card title="By category">{s && <Breakdown data={s.by_category} />}</Card>
        <Card title="Verdicts">
          {s && (
            <Breakdown data={s.by_verdict} order={["approve", "comment", "request_changes"]} colorPrefix="verdict" />
          )}
        </Card>
      </div>

      <div className="grid-2">
        <Card title="Recent reviews" action={<Link to="/reviews" className="link">View all →</Link>}>
          {recent.data?.items.length === 0 && <Empty>No reviews yet. Open a pull request on a repo where the app is installed.</Empty>}
          <ul className="recent">
            {recent.data?.items.map((r) => (
              <li key={r.id}>
                <Link to={`/reviews/${r.id}`}>
                  <div className="recent-main">
                    <span className="recent-title">{r.pr_title || `PR #${r.pr_number}`}</span>
                    <span className="mono muted small">
                      {r.repo_full_name}#{r.pr_number} · {timeAgo(r.created_at)}
                    </span>
                  </div>
                  {r.status === "completed" ? <VerdictBadge verdict={r.verdict} /> : <StatusBadge status={r.status} />}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Most active repositories">
          {s && s.top_repos.length === 0 && <Empty>No data yet</Empty>}
          <ul className="repos">
            {s?.top_repos.map((r) => (
              <li key={r.repo}>
                <Link to={`/reviews?repo=${encodeURIComponent(r.repo)}`} className="mono">{r.repo}</Link>
                <span className="muted">{r.reviews} reviews</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
