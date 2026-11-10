import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Comment } from "../api";
import { Card, Empty, ErrorBox, SeverityDot, StatusBadge, VerdictBadge } from "../components";
import { compact, formatDuration, timeAgo, useAsync } from "../hooks";

const SEV_ORDER = { error: 0, warning: 1, info: 2 } as const;

function groupByFile(comments: Comment[]) {
  const groups = new Map<string, Comment[]>();
  for (const c of [...comments].sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity])) {
    groups.set(c.path, [...(groups.get(c.path) ?? []), c]);
  }
  return [...groups.entries()];
}

export default function ReviewDetail() {
  const id = Number(useParams().id);
  const [filter, setFilter] = useState<string>("all");
  const [retrying, setRetrying] = useState(false);
  const { data: r, error, refresh } = useAsync(() => api.review(id), [id], (d) =>
    d.status === "queued" || d.status === "running",
  );

  if (error) return <ErrorBox message={error} />;
  if (!r) return <div className="page"><div className="skeleton tall" /></div>;

  const shown = r.comments.filter((c) => filter === "all" || c.severity === filter);
  const counts = { error: 0, warning: 0, info: 0 } as Record<string, number>;
  r.comments.forEach((c) => counts[c.severity]++);

  const retry = async () => {
    setRetrying(true);
    try {
      await api.retry(id);
      refresh();
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="page">
      <Link to="/reviews" className="link small">← All reviews</Link>
      <div className="page-head">
        <div>
          <h1>{r.pr_title || `PR #${r.pr_number}`}</h1>
          <p className="mono muted small">
            {r.repo_full_name}#{r.pr_number} · {r.head_sha.slice(0, 7)}
            {r.pr_author && ` · @${r.pr_author}`} · {timeAgo(r.created_at)}
          </p>
        </div>
        <div className="head-actions">
          <StatusBadge status={r.status} />
          {r.status === "completed" && <VerdictBadge verdict={r.verdict} />}
          {r.pr_url && <a className="button" href={r.pr_url} target="_blank" rel="noreferrer">Open on GitHub ↗</a>}
          {(r.status === "failed" || r.status === "completed" || r.status === "skipped") && (
            <button onClick={retry} disabled={retrying}>{retrying ? "Queuing…" : "Re-run review"}</button>
          )}
        </div>
      </div>

      {r.error && <div className="error-box">{r.error}</div>}

      <div className="meta-row">
        <div><span>Files</span>{r.files_reviewed}</div>
        <div><span>Lint findings</span>{r.lint_issue_count}</div>
        <div><span>Tests</span><span className="cap">{r.tests_status ?? "—"}</span></div>
        <div><span>Duration</span>{formatDuration(r.duration_ms)}</div>
        <div><span>Tokens</span>{compact(r.tokens_in + r.tokens_out)}</div>
        <div><span>Model</span><span className="mono">{r.model ?? "—"}</span></div>
      </div>

      <Card title="Summary">
        {r.summary ? <p className="summary">{r.summary}</p> : <Empty>{r.status === "completed" ? "No summary." : "The review hasn't finished yet."}</Empty>}
      </Card>

      <Card
        title={`Issues (${r.comments.length})`}
        action={
          <div className="seg">
            {["all", "error", "warning", "info"].map((f) => (
              <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
                {f !== "all" && <SeverityDot severity={f} />}
                {f} {f !== "all" && <span className="muted">{counts[f]}</span>}
              </button>
            ))}
          </div>
        }
      >
        {shown.length === 0 && <Empty>No issues{filter !== "all" ? ` with severity "${filter}"` : ""}.</Empty>}
        {groupByFile(shown).map(([path, items]) => (
          <div className="file-group" key={path}>
            <div className="file-path mono">{path}</div>
            {items.map((c) => (
              <article className={`issue sev-border-${c.severity}`} key={c.id}>
                <div className="issue-meta">
                  <SeverityDot severity={c.severity} />
                  <span className="mono">{c.line ? `L${c.line}` : "file"}</span>
                  <span className="tag">{c.category}</span>
                  <span className={`tag tag-${c.source}`}>{c.source === "lint" ? "linter" : "AI"}</span>
                  {!c.posted_inline && <span className="muted small">in summary</span>}
                </div>
                <p>{c.body}</p>
              </article>
            ))}
          </div>
        ))}
      </Card>
    </div>
  );
}
