# Changelog

All notable changes to Daily Code Learn are documented here.

## Unreleased

### Changed

- Regenerate yesterday's report before building the scrum, so `/scrum` no longer misses every commit made after the previous morning's run. `--check-missed` skips any date that already has a report directory, so the work committed after yesterday's run stayed invisible and today's standup silently repeated the day before yesterday.

## v0.2.1 - 2026-09-11

### Changed

- Require a verbatim project identity and commit hash in the analysis coverage table and in detail-section titles, so a claim can be traced with `git show` and so `/dig` can tell which project a detail section belongs to.
- Bound the `/dig` timeline index to the last 90 days; it grew with every analysis and was already consuming tens of thousands of tokens before the first question.
- Let `/scrum` expand a long multi-task commit into sub-bullets instead of truncating it at 80 characters, which dropped most of what a multi-hour commit actually contained.
- Isolate `PROJECT_ROOT` and assert environment state inside the patched environment in configuration tests, so a real `.env` in the working tree no longer makes `_load_env` and `--doctor` tests fail.

### Notes

- The coverage table gains a `커밋` column and detail-section titles gain a `[root/repo hash]` prefix. Analyses written before this version keep the old shape, so an existing reports directory holds both. `/dig` reads past analyses by grepping the project's last path segment, which still matches either shape.
- These changes take effect on the next `/analyze` run. Nothing rewrites existing analysis files.

## v0.2.0 - 2026-09-10

### Added

- Add the `/analyze` skill for Claude Code and Codex, which reads every report for a day, writes a learning analysis following `prompts/analyze.md`, and sends it through Telegram when enabled.
- Add the `/dig` skill, which opens a follow-up conversation about one project's diff for a day, recalls what the user did not know from earlier `/dig` sessions on the same project, reads the repository's source when the diff alone cannot answer a question, and cross-references the project's rows across every past analysis.
- Add the `/publish` skill, which closes a `/dig` conversation by recording what the user did not know as question, one-line answer, and takeaway under `reports/dig/{root--repo}/{date}.md`, and never invents entries when nothing was asked.
- Add the `/scrum` skill and the optional `scrum` configuration block, which summarize the last working day plus the current morning for one workspace, grouped by project, with ticket IDs and `#time` values copied verbatim from commit titles, for a morning standup.

### Changed

- Generate deterministic report filenames from root-relative identities, embed a full identity marker, and fail safely on in-run filename collisions or non-matching, symbolic-link, and special-file targets, while retaining legacy project-only reports without migrating or deleting them.
- Include current staged, unstaged, and untracked changes only for today's report by default; historical runs can opt in with `--include-current-changes`.
- Use local-timezone committer dates consistently for filtering, display, and missed-day aggregation, with a full `--since-as-filter` revision walk, NUL-delimited metadata fields, epoch-based newest-first sorting, and deduplicated author results.
- Add depth-bounded nested repository discovery and linked-worktree support through `roots[].maxDepth`, with inode-based `--doctor` validation of usable worktrees and cross-root real-repository uniqueness, including case and symlink aliases.
- Use one validated configuration contract for normal runs and `--doctor`.
- Surface repository Git/fetch failures and return a non-zero status for incomplete collection while preserving successful reports.
- Use repository-relative metadata and omit author email addresses from generated reports.
- Atomically replace and fsync generated reports through anchored directory descriptors with owner-only file permissions, retain and revalidate an inode-bound previous version during replacement, preserve ambiguous-failure recovery artifacts, create and durably record private date directories, and refuse directories outside the current-user/non-writable security boundary.
- Exclude common environment, private-key, and credential files by default unless `report.includeSensitiveFiles` is enabled.
- Retain diff output within configurable line and byte limits, report the original configured limit across pathspec chunks, split large pathspec sets into bounded Git commands, preserve undecodable filename bytes safely, and filter rename paths from NUL-delimited Git metadata.
- Make exclude matching segment-aware and treat Git-looking filenames as literal paths.
- Keep every Telegram HTML message within the 4096-character transport limit using conservative UTF-16 accounting, cap a file at 100 messages before partial delivery, require a successful API response, neutralize display controls, omit internal report identity markers, reject symbolic-link, special-file, and over-8-MiB inputs, fail explicit sends when disabled, and avoid echoing token-bearing transport URLs in errors.
- Limit `--notify` delivery to report files written by the current run and bind each delivery to its write-time directory inode, file inode, and SHA-256 content.
- Load Telegram credentials only from an owner-only regular `.env` or pre-existing environment variables, refuse unsafe `.env` ownership, permissions, and symlinks, and discard credential-looking runtime values persisted in `profiles.json`.
- Detect generated reports by a dated header plus a current identity marker or legacy report structure during missed-day checks, surface output-read failures, and bound `--days` to 1 through 3650.
- Escape terminal, log, report-diff, Unicode direction, and line-separator controls, including undecodable filename bytes, before displaying or writing untrusted text; reject symbolic-link date directories across generation, missed-day checks, and notification.
- Require Git 2.37.0 or newer for complete date-filter traversal and verify it through `--doctor`.
- Test Python 3.10 through 3.14 on Linux and include a macOS smoke test in CI.

### Documentation

- Document Git and Python requirements, scan depth, exclude semantics, output identity, overwrite behavior, exit codes, `NO_COLOR`/`FORCE_COLOR`, and data-safety defaults in English and Korean.
- Document independent line and byte diff limits, filesystem publication requirements and recovery, plus the direct-notifier trust boundary in English and Korean.
- Direct vulnerability reports to GitHub private security advisories instead of public issues.
- Document the shipped skills, the `reports/dig/` layout, and the `scrum` configuration in English and Korean.

### Notes

- Reports generated by v0.1.0 at `reports/{date}/{project}.md` are left in place and still count as generated days. New reports use the collision-resistant `root--repo--hash` filename, so both forms coexist in an existing reports directory.
- Skills run only inside a Claude Code or Codex session. The CLI itself still depends on the Python standard library alone.
- The `scrum` configuration block is read only by the `/scrum` skill and is not validated by `--doctor`.

## v0.1.0 - 2026-06-30

Initial public release.

### Added

- Generate daily Markdown reports from Git commits and working tree changes.
- Scan multiple workspace roots for Git repositories.
- Include commit diffs, staged diffs, unstaged diffs, and untracked file lists.
- Exclude generated files and lockfiles from reports through config patterns.
- Check missed report days with `--check-missed`.
- Send Markdown analysis files to Telegram when enabled.
- Initialize local config with `--init`.
- Diagnose common setup problems with `--doctor`.
- Print the CLI version with `--version`.

### Notes

- Daily Code Learn currently runs as a source checkout with `python3 generate.py`.
- The project intentionally uses only the Python standard library.
- Generated reports may include sensitive local code diffs. Review config and output before sharing.
