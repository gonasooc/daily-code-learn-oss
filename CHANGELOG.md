# Changelog

All notable changes to Daily Code Learn are documented here.

## Unreleased

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
