import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Empty, ErrorBox, StatusBadge, VerdictBadge } from "../components";
import { formatDuration, timeAgo, useAsync } from "../hooks";

const PAGE = 20;
const STATUSES = ["", "completed", "running", "queued", "failed", "skipped"];

export default function Reviews() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const repo = params.get("repo") ?? "";
  const status = params.get("status") ?? "";
  const page = Number(params.get("page") ?? 0);

  const repos = useAsync(api.repos, []);
  const list = useAsync(
    () => api.reviews({ repo, status, limit: PAGE, offset: page * PAGE }),
    [repo, status, page],
    (d) => d.items.some((r) => r.status === "queued" || r.status === "running"),
  );

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  };

  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Reviews</h1>
          <p className="muted">{total} review{total === 1 ? "" : "s"}</p>
        </div>
        <div className="filters">
          <select value={repo} onChange={(e) => update("repo", e.target.value)} aria-label="Repository">
            <option value="">All repositories</option>
            {repos.data?.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <select value={status} onChange={(e) => update("status", e.target.value)} aria-label="Status">
            {STATUSES.map((s) => <option key={s} value={s}>{s || "Any status"}</option>)}
          </select>
        </div>
      </div>

      {list.error && <ErrorBox message={list.error} />}

      <div className="card table-card">
        <table>
          <thead>
            <tr>
              <th>Pull request</th>
              <th>Status</th>
              <th>Verdict</th>
              <th className="num">Issues</th>
              <th className="num hide-sm">Files</th>
              <th className="num hide-sm">Time</th>
              <th className="hide-sm">Created</th>
            </tr>
          </thead>
          <tbody>
            {list.data?.items.map((r) => (
              <tr key={r.id} onClick={() => navigate(`/reviews/${r.id}`)}>
                <td>
                  <Link to={`/reviews/${r.id}`} className="cell-title" onClick={(e) => e.stopPropagation()}>
                    {r.pr_title || `PR #${r.pr_number}`}
                  </Link>
                  <div className="mono muted small">
                    {r.repo_full_name}#{r.pr_number} · {r.head_sha.slice(0, 7)}
                    {r.pr_author && ` · @${r.pr_author}`}
                  </div>
                </td>
                <td><StatusBadge status={r.status} /></td>
                <td><VerdictBadge verdict={r.verdict} /></td>
                <td className="num">{r.comment_count}</td>
                <td className="num hide-sm">{r.files_reviewed}</td>
                <td className="num hide-sm">{formatDuration(r.duration_ms)}</td>
                <td className="hide-sm muted">{timeAgo(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.data?.items.length === 0 && <Empty>No reviews match these filters.</Empty>}
      </div>

      {pages > 1 && (
        <div className="pager">
          <button disabled={page === 0} onClick={() => update("page", String(page - 1))}>← Prev</button>
          <span className="muted">Page {page + 1} of {pages}</span>
          <button disabled={page + 1 >= pages} onClick={() => update("page", String(page + 1))}>Next →</button>
        </div>
      )}
    </div>
  );
}
