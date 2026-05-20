# Tier 3 Setup Runbook

Four items the user opted into. #1 is fully shipped in code. #2-#4 are configuration in third-party dashboards or GitHub App installs that require the user's admin credentials. This document is the step-by-step.

---

## 3.1 Secret scanning ✅ DONE

Status: shipped as `.github/workflows/gitleaks.yml` in the moreway-orbit repo. Runs on every PR + push to main. Fails the workflow if any committed secret is detected.

Nothing for the user to do. Verification: open PR #44 (or the next PR) and check the "Gitleaks (secret scanning)" job at the bottom of the checks list.

If you ever want to allowlist a known-OK string (e.g. a public placeholder), drop a `.gitleaks.toml` at the repo root with an `[[rules]]` exception. See gitleaks docs: https://github.com/gitleaks/gitleaks#configuration

---

## 3.2 Cost monitoring (Vercel + Neon billing alerts)

Pure dashboard config. ~10 minutes total.

### Vercel

1. Open the Moreway Orbit project: https://vercel.com/k0mrads-projects/moreway-orbit/settings/billing
2. Set a **monthly budget** at the dollar amount you want to cap.
3. Enable email notifications at 50%, 75%, 90%, 100% of budget.
4. (Optional, Pro plan and above) Add a Slack webhook for the same thresholds. Settings → Notifications → "Add Slack integration" → point at `#ads-audits`.

The Vercel dashboard's Usage tab also shows per-deployment function-time consumption. Worth a weekly glance to catch runaway endpoint usage.

### Neon

1. Open the Neon project containing Orbit's DB: https://console.neon.tech/
2. Settings → Billing → enable monthly budget alert (Free tier is hard-capped; Pro tier lets you set a soft limit).
3. Operations → Quotas: confirm `compute_time_seconds` and `data_transfer_bytes` limits match your tier. Set alert thresholds at 75% and 90%.

There is no Slack-native integration for Neon at the free tier; emails are the only channel.

### What this catches

- A buggy query that suddenly does a full-table scan and burns Neon compute time.
- A new endpoint that gets called more than expected and inflates Vercel function-invocation counts.
- Andy's own audit invocations getting too aggressive (the morning routine should fit comfortably in the free tier; if it doesn't, something's wrong with andy).

---

## 3.3 Error-rate monitoring (Vercel Analytics + alert rules)

Vercel has built-in error-rate tracking. Light-touch, no third-party SaaS.

### Enable Web Analytics + Speed Insights

1. Open the Moreway Orbit project: https://vercel.com/k0mrads-projects/moreway-orbit/analytics
2. Click "Enable Web Analytics" if not already on. Free tier covers low-volume usage; upgrade if you exceed the included events.
3. The Functions tab shows per-endpoint 4xx and 5xx counts per hour.

### Alert rules

Vercel's alerting requires the Pro plan or above. If you have it:

1. Settings → Notifications → "Function Errors" alert.
2. Threshold: `>5 errors in 10 minutes for any function under api/ads/*`.
3. Channel: email or Slack webhook to `#ads-audits`.

If you don't have Pro: andy's morning routine effectively catches sustained sync failures via the Tier 1.2 real-time Slack ping I already shipped. The gap that Vercel Analytics would close is *intermittent 5xx spikes that don't crash the sync* (e.g. a transient timeout on `/api/ads/drilldown/*` that the user sees but the orchestrator doesn't). The morning Slack post + the e2e smoke job catch the next-day version. A real-time spike alert is nice-to-have, not critical.

### Cheaper alternative: Sentry

If Vercel Pro isn't worth it just for error alerts, Sentry's free tier (5k events/month) is enough for an internal app like Orbit. Setup:

1. Sign up at https://sentry.io, create a project for "Vercel Serverless".
2. `npm install --save @sentry/nextjs` (or `@sentry/serverless` for plain Vercel).
3. Wrap `api/ads/*.ts` handlers with `Sentry.captureException(err)` in their catch blocks.
4. Sentry's dashboard does per-endpoint error grouping + Slack-native alerting in the free tier.

Skipping this entirely is OK too — andy's Tier 1.2 Slack alerts cover the sync hot path. Only revisit if you start seeing user-visible 5xx that the sync layer doesn't catch.

---

## 3.4 /andy-reviews-pr — PR-time code review

The most consequential Tier 3 item. Two paths; pick one.

### Path A (recommended): install the official Claude Code GitHub App

Anthropic publishes a GitHub App that reviews PRs against any custom instructions you provide. It auto-fires on PR open + on every push to the PR.

1. Open https://github.com/apps/claude and click "Install".
2. Select the `moreway-orbit` repository.
3. Authorize with your Anthropic API key. The app uses your billing.
4. In the repo, add `.claude/code-review-instructions.md`:
   ```markdown
   # PR Review Instructions for Andy

   When reviewing a PR in this repo, you act as andy-the-auditor would. Read:
   - https://raw.githubusercontent.com/k0mrads/andy-the-auditor/main/invariants/orbit.md
   - https://raw.githubusercontent.com/k0mrads/andy-the-auditor/main/SKILL.md

   Then review the diff with these priorities:

   1. **Golden rule**: any new query against `ads_paid_leads` MUST filter on `last_paid_opt_in_at`. Flag uses of `created_at`, `dateAdded`, or `first_paid_opt_in_at` near `ads_paid_leads`.
   2. **Paid predicate**: `isLastTouchPaid()` should be defined exactly once at `api/ads/_ghl-direct.ts:69`. Flag any re-implementation.
   3. **UNION semantics**: any change to `paidConversionsByObject()` at `api/ads/_drilldown-sql.ts:98-156` requires explicit justification.
   4. **Window math**: any new SQL touching `ads_paid_leads.last_paid_opt_in_at` or `ads_paid_bookings.booked_at` must use `clientWindow(timezone, ...)`, never bare YYYY-MM-DD strings.
   5. **Schema changes**: any modification to `drizzle/schema.ts` tracked tables (ads_clients_config, ads_meta_*, ads_paid_*, ads_sync_log) requires updating andy's baseline via `~/.claude/skills/andy-the-auditor/scripts/regen-baselines.sh` and committing the result to the skill repo.
   6. **New endpoints**: any new `api/ads/*.ts` route must be added to `invariants/orbit.md` "Known endpoints" list (ORBIT-H6).
   7. **Scope discipline**: NEVER include marketing-performance commentary in the review (spend trends, creative effectiveness, ROAS observations). Andy is dev-only.

   Output format: a single PR comment with sections (BLOCKERS, WARNINGS, INFO). Be terse. File:line refs for every flag. No "looks good overall" preambles.

   Hard rules:
   - Never use em dashes; use commas, periods, colons, parentheses.
   - If the diff is purely cosmetic (formatting, comments, no logic), respond with one line: "Cosmetic only, no andy concerns."
   ```
5. Commit + push. Next PR opened against main will get an automated andy-style review comment.

### Path B (custom GHA, more control, more code)

If the GitHub App's billing model doesn't fit, you can do the same thing with a custom workflow using the `@anthropic-ai/claude-code-action`:

```yaml
name: Andy PR Review
on: pull_request
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: anthropic/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          system_prompt: |
            You are andy-the-auditor reviewing a PR in the Moreway Orbit
            Ads Command Center. Pull the invariants from
            https://raw.githubusercontent.com/k0mrads/andy-the-auditor/main/invariants/orbit.md
            and review the diff against those rules. Output a single PR
            comment. (See full instructions inlined in this workflow.)
          [...rest matches Path A's instructions...]
```

This requires the action to exist in the form I'm describing. If it doesn't (Anthropic action surface changes), the GitHub App path is the supported one.

### What this catches

A new PR that:
- Introduces a `created_at` window filter on `ads_paid_leads` (golden rule violation).
- Adds a new sync endpoint without registering it in invariants.
- Modifies `_ghl-direct.ts` paid predicate without updating the invariants doc.
- Bypasses `clientWindow()` and passes bare date strings to Meta.

The GHA workflow (Tier 1.1) catches some of these via static greps. The PR review catches the *semantic* violations the grep would miss (e.g. a clever variable rename that makes the grep pass but the logic still violates the rule).

---

## Verification (after setup)

1. **Gitleaks**: open any PR. Confirm "Gitleaks" job appears in the checks list. Try pushing a commit with a fake `xoxb-fake-token-1234567890` to a test branch; the job should fail. Revert.
2. **Vercel billing**: trigger a tiny budget alert (set $0.01 budget temporarily); confirm email arrives. Reset budget to real value.
3. **Neon billing**: same approach as Vercel.
4. **Vercel Analytics**: open the dashboard, generate some traffic, confirm functions tab shows requests.
5. **Sentry** (if installed): manually throw an error in a non-production endpoint, confirm Sentry receives it.
6. **Andy PR review**: open a small no-op PR. Confirm the bot comments within 2-3 minutes.

When all six tick, Tier 3 is locked in.

---

*Maintained by /andy-the-auditor.*
