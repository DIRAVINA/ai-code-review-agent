# Connecting the agent to GitHub

This guide takes you from zero to a bot that comments on your pull requests. It takes about 15 minutes. You need Python 3.11+, Node 20+, and either Docker Desktop (easiest) or a local Redis.

## 1. Get a public URL for webhooks (smee.io)

GitHub has to reach your laptop. [smee.io](https://smee.io) forwards webhooks for free, with no account needed.

1. Open https://smee.io and click **Start a new channel**.
2. Copy the URL, for example `https://smee.io/AbC123xyz`. You'll use it in step 2 and step 5.

## 2. Create the GitHub App

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
   (direct link: https://github.com/settings/apps/new).
2. Fill in:
   - **GitHub App name:** something unique, e.g. `diravina-review-bot`
   - **Homepage URL:** your repo URL
   - **Webhook URL:** your smee.io URL
   - **Webhook secret:** any long random string. Generate one with
     `python -c "import secrets; print(secrets.token_hex(32))"` and **save it**.
3. **Repository permissions:**
   - **Contents:** Read-only
   - **Pull requests:** Read and write
   - **Metadata:** Read-only (selected automatically)
4. **Subscribe to events:** tick **Pull request**.
5. **Where can this app be installed?** Only on this account.
6. Click **Create GitHub App**.

On the app's page:

7. Note the **App ID** near the top.
8. Scroll to **Private keys** → **Generate a private key**. A `.pem` file downloads.
   Move it to `backend/secrets/github-app.pem`. That folder is git-ignored, so the key never gets committed.

## 3. Install the app on a repository

1. On the app's page, click **Install App** in the left sidebar → **Install**.
2. Choose **Only select repositories** and pick a test repo, or create a new one.

## 4. Configure the backend

```bash
cd backend
cp .env.example .env
```

Edit `backend/.env`:

```env
GITHUB_APP_ID=123456                      # from step 2.7
GITHUB_PRIVATE_KEY_PATH=./secrets/github-app.pem
GITHUB_WEBHOOK_SECRET=the-secret-from-step-2

# Start with the free offline reviewer to test the plumbing:
LLM_PROVIDER=fake

# Then switch to a real model:
# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-ant-...            # https://console.anthropic.com
# or
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-...
```

## 5. Run everything

**Option A: Docker (recommended).** From the repo root:

```bash
docker compose up --build
```

**Option B: without Docker.** You need Redis running locally (`redis-server`). Then use three terminals, each starting from `backend/` with the venv active:

```bash
uvicorn app.main:app --reload            # terminal 1: API
arq app.worker.WorkerSettings            # terminal 2: worker
cd ../frontend && npm run dev            # terminal 3: dashboard
```

**Then forward webhooks** in one more terminal:

```bash
npx smee-client --url https://smee.io/AbC123xyz --target http://localhost:8000/webhooks/github
```

## 6. Test it

1. In the repo where you installed the app, create a branch, add a file with something questionable, and open a pull request:

   ```python
   import os

   def run(cmd):
       try:
           return eval(cmd)
       except:
           print("failed")
   ```

2. Within a few seconds, the worker logs `Review 1 completed`, and the PR shows a review with inline comments.
3. Open the dashboard (http://localhost:3000 with Docker, http://localhost:5173 without) to see it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Webhook returns **401** | `GITHUB_WEBHOOK_SECRET` doesn't match the app's secret. |
| Nothing happens on a new PR | Is smee-client running? Check **App settings → Advanced → Recent Deliveries**. Draft PRs are skipped on purpose. |
| Review status **failed** with 401/404 from GitHub | Wrong App ID or key, or the app isn't installed on that repo. |
| Review **failed** with an LLM error | Check the API key and that `LLM_PROVIDER` matches it. |
| Status stuck on **queued** | The worker isn't running, or it can't reach Redis. |

You can redeliver any webhook from **Recent Deliveries**, and re-run any review from the dashboard.
