# Changelog

All notable changes to Daily Code Learn are documented here.

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
