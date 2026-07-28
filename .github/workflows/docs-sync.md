---
emoji: 📚
description: Daily check that repository documentation stays in sync with recent code changes; opens a pull request with the needed doc updates.
on:
  schedule: daily
  workflow_dispatch:
permissions:
  contents: read
checkout:
  fetch-depth: 0  # full git history (matches GitHub's official gh-aw samples) so the agent can inspect recent commits
safe-outputs:
  create-pull-request:
    title-prefix: "[docs-sync] "
    labels: [documentation, automation]
    draft: true
    if-no-changes: "ignore"
    allowed-files:
      - "**/*.md"
---

# Documentation Sync

## Context

This workflow runs daily. Your job is to keep the repository documentation in sync
with recent code changes and open a pull request with any needed updates.

The repository is a public "Agentic IT Ops" use-case collection. Documentation
(`README.md`, `docs/**`, `usecases/**/README.md`, and other `*.md` files) must
stay consistent with the actual code, scripts, agents, prompts, and instructions.

## Task

1. Determine the review window. Inspect commits from roughly the **last 24 hours**
   (or since the previous scheduled run) using `git log`, e.g.
   `git log --since="24 hours ago" --name-status`. The repository is checked out
   with full history (`fetch-depth: 0`), so this range is available; if the
   command returns nothing, double-check with `git log -20 --name-status`
   before concluding there are no changes. If there are genuinely no relevant
   code/config changes, stop and call `noop` with a short explanation.
2. For each meaningful change (new/removed/renamed files, changed behavior,
   updated commands, altered structure, new agents/prompts/instructions),
   identify which documentation files describe that area.
3. Compare the documentation against the current code and flag anything that is
   **out of sync**: stale instructions, wrong file paths, removed/renamed items
   still referenced, missing coverage of new features, outdated commands or
   examples, and broken internal links.
4. Edit the affected Markdown files to bring them back in sync. Make the smallest
   correct changes; do not rewrite unrelated content or restructure docs beyond
   what the code changes require.
5. Follow the repository conventions: documentation is written in **Japanese**;
   never include secrets or real identifiers—use placeholders such as
   `<SUBSCRIPTION_ID>`, `<TENANT_ID>`, `<RESOURCE_GROUP>`, `<RESOURCE_NAME>`,
   `<REGION>`.
6. Open a single pull request using the `create-pull-request` safe output. In the
   PR body, summarize (in Japanese) which docs changed and which code changes
   drove each update, referencing the relevant commits.

## Safe Outputs

- Use the configured `create-pull-request` safe output to propose documentation
  changes. Only Markdown files are allowed.
- If no documentation is out of sync, call `noop` with a brief explanation
  instead of opening an empty pull request.
