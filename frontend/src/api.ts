export type Severity = "error" | "warning" | "info";

export interface Comment {
  id: number;
  path: string;
  line: number | null;
  severity: Severity;
  category: string;
  source: "llm" | "lint";
  body: string;
  posted_inline: boolean;
}

export interface Review {
  id: number;
  repo_full_name: string;
  pr_number: number;
  pr_title: string;
  pr_author: string;
  pr_url: string;
  head_sha: string;
  status: "queued" | "running" | "completed" | "failed" | "skipped";
  verdict: "approve" | "comment" | "request_changes" | null;
  model: string | null;
  files_reviewed: number;
  lint_issue_count: number;
  tests_status: string | null;
  tokens_in: number;
  tokens_out: number;
  attempts: number;
  duration_ms: number | null;
  created_at: string;
  completed_at: string | null;
  comment_count: number;
}

export interface ReviewDetail extends Review {
  summary: string | null;
  error: string | null;
  comments: Comment[];
}

export interface Stats {
  total_reviews: number;
  total_issues: number;
  avg_duration_ms: number | null;
  total_tokens: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
  by_category: Record<string, number>;
  by_verdict: Record<string, number>;
  per_day: { day: string; reviews: number; issues: number }[];
  top_repos: { repo: string; reviews: number }[];
}

const BASE = import.meta.env.VITE_API_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  stats: () => request<Stats>("/api/stats"),
  repos: () => request<string[]>("/api/repos"),
  reviews: (params: { repo?: string; status?: string; limit?: number; offset?: number }) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && q.set(k, String(v)));
    return request<{ items: Review[]; total: number }>(`/api/reviews?${q}`);
  },
  review: (id: number) => request<ReviewDetail>(`/api/reviews/${id}`),
  retry: (id: number) => request<{ ok: boolean }>(`/api/reviews/${id}/retry`, { method: "POST" }),
};
