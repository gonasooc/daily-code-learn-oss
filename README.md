# Daily Code Learn

<p align="center">
  <img src="docs/thumbnail.svg" alt="Daily Code Learn" width="100%">
</p>

[Korean README](docs/README.ko.md)

Daily Code Learn is a zero-dependency Python CLI that turns your daily Git activity into Markdown learning reports.

Run one terminal command before you finish work, and it scans your configured workspaces for repositories with activity, then writes one Markdown report per project. The generated reports are designed to be sent to Claude, Codex, or another LLM for learning-oriented analysis.

## Requirements

- Git 2.37.0 or newer, available on `PATH`
- Python 3.10 or newer (CI tests Python 3.10 through 3.14)
- macOS or Linux
- An `outputDir` filesystem that supports same-directory hard links, atomic
  replacement, and directory `fsync`

## Features

- Uses only the Python standard library. No runtime dependencies.
- Scans direct Git repositories by default and supports bounded recursive discovery with `roots[].maxDepth`.
- Recognizes regular repositories (`.git` directory) and linked worktrees (`.git` file).
- Runs `git fetch` before collecting commits, so commits pushed from another machine can be detected without running `git pull`.
- Captures commit history, staged changes, unstaged changes, and untracked file lists.
- Includes configurable diffs for committed and uncommitted changes.
- Keeps report names collision-resistant with a readable repository identity and deterministic hash.
- Detects missed report days with `--check-missed`.
- Can send generated analysis Markdown to Telegram when enabled.
- Ships Claude Code and Codex skills — `/analyze`, `/dig`, `/publish`, `/scrum` — that turn reports into learning notes, per-project follow-up sessions, and standup summaries.

## Quickstart

```bash
git clone https://github.com/gonasooc/daily-code-learn-oss.git
cd daily-code-learn-oss

# Create your local config file.
python3 generate.py --init

# Edit config/profiles.json:
# - roots[].path
# - roots[].authorNames
# - roots[].authorEmails

# Check your setup.
python3 generate.py --doctor

# Generate today's reports.
python3 generate.py
```

Reports are written to:

```text
reports/{date}/{root--repository-relative-slug}--{16-character-hash}.md
```

The ASCII-readable slug is derived from `root-name--repository-relative-path`,
uses `--` for path boundaries, replaces other unsafe character runs with `-`,
and is capped at 160 characters. The suffix is the first 16 hexadecimal
characters of SHA-256 over the exact root/repository identity, giving truncated
or normalized names a stable discriminator. A current run fails instead of
overwriting if two final filenames still collide. Local absolute paths are not
used in filenames or report metadata.

## Commands

```bash
# Print the current version.
python3 generate.py --version

# Create config/profiles.json from the example config.
python3 generate.py --init

# Check Git, config, workspace paths, author values, and Telegram env vars.
python3 generate.py --doctor

# Generate reports for today.
python3 generate.py

# Generate reports for a specific date.
python3 generate.py --date 2026-03-12

# Include the current working tree in a historical-date report.
python3 generate.py --date 2026-03-12 --include-current-changes

# Generate reports and send them through Telegram if Telegram is enabled.
python3 generate.py --notify

# Find recent work days that do not have reports yet.
python3 generate.py --check-missed

# Check the last 14 days instead of the default 30 days.
python3 generate.py --check-missed --days 14

# Show detailed collection diagnostics, including Git failures.
python3 generate.py --verbose
```

`--check-missed` does more than list missing days. After you select a missed day, it immediately generates reports for that date.
`--days` accepts values from 1 through 3650.

ANSI color is enabled only for supported terminals. Define the standard
`NO_COLOR` environment variable to disable it. `FORCE_COLOR=1` enables color
for redirected output, while `FORCE_COLOR=0` explicitly disables it:

```bash
NO_COLOR=1 python3 generate.py
FORCE_COLOR=1 python3 generate.py
```

## Configuration

Create a local config:

```bash
python3 generate.py --init
```

Then edit `config/profiles.json`:

```json
{
  "roots": [
    {
      "name": "my-workspace",
      "path": "/path/to/repositories",
      "maxDepth": 2,
      "authorNames": ["My Name"],
      "authorEmails": ["my@email.com"]
    }
  ],
  "outputDir": "./reports",
  "report": {
    "includeUncommittedDiff": true,
    "includeSensitiveFiles": false,
    "maxDiffLines": 1200,
    "maxDiffBytes": 2097152
  },
  "exclude": [
    "node_modules",
    ".next",
    "dist",
    "build",
    "coverage",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml"
  ],
  "telegram": {
    "enabled": false
  },
  "scrum": {
    "root": "my-workspace",
    "outputDir": "/path/to/notes/scrum"
  }
}
```

`reports/` and `config/profiles.json` are local files and are ignored by Git.

Run the setup checker after editing config:

```bash
python3 generate.py --doctor
```

`--doctor` checks:

- whether Git 2.37.0 or newer is available on `PATH`
- whether `config/profiles.json` exists and can be parsed
- whether fields have the expected types and allowed values
- whether each `roots[].path` exists
- whether discovered `.git` markers are usable Git worktrees, and how many
  unique usable repositories and linked worktrees remain within each root's
  configured depth (zero is reported as a setup failure)
- whether the same real repository is discovered under more than one
  configured root
- whether root names are non-empty and unique and author filters are non-empty
- whether `outputDir` can be created, read, written, and traversed
- whether Telegram environment variables are present when Telegram is enabled

The schema, path, and writability validation also runs before normal report
generation, and invalid configuration stops before repositories are scanned.
`--doctor` adds setup-oriented checks for placeholder author values and Telegram
environment variables.

| Field | Description |
| --- | --- |
| `roots[].name` | Unique workspace label used in terminal and report paths |
| `roots[].path` | Directory scanned for Git repositories and worktrees |
| `roots[].maxDepth` | Maximum discovery depth; direct children are depth `1`. Default: `1` |
| `roots[].authorNames` | Git author names for report metadata |
| `roots[].authorEmails` | Git author emails combined as an OR filter for commits |
| `outputDir` | Directory where reports are written |
| `report.includeUncommittedDiff` | Whether staged and unstaged diffs are included. Default: `true` |
| `report.includeSensitiveFiles` | Allow commonly sensitive files into report data. Default: `false` |
| `report.maxDiffLines` | Maximum diff lines per block; `0` disables the line limit while the byte limit still applies. Default: `1200` |
| `report.maxDiffBytes` | Maximum raw diff bytes retained per block; `0` disables the byte limit. Default: `2097152` (2 MiB) |
| `exclude` | Glob/path patterns excluded from file lists and diff output |
| `telegram.enabled` | Whether Telegram sending is enabled. Default: `false` |
| `scrum.root` | Optional. The `roots[].name` whose repositories the `/scrum` skill summarizes |
| `scrum.outputDir` | Optional. Directory where `/scrum` writes `{date}.md`, usually a notes folder outside `reports/` |

`roots[].path` may point to a repository itself or to a directory that contains
repositories. Scanning stops below a directory as soon as that directory is
recognized as a repository. Increase `maxDepth` when repositories are grouped
in intermediate folders; the bound prevents unrelated deep trees from being
traversed. Duplicate or overlapping root paths are rejected by filesystem
identity, including aliases whose spelling or case differs, to avoid processing
the same repository twice.

Exclude matching is repository-relative and case-sensitive. A pattern without
`/` is matched against each complete path segment, so `dist` excludes a
directory named `dist` but not `distribution`; shell-style patterns such as
`*.lock` work the same way. A pattern containing `/` is matched against the
whole repository-relative path and directory-aligned suffixes. Excludes apply
to file lists and complete diff blocks; for a detected rename, excluding either
the old or new path omits that whole diff block.

The built-in safety baseline excludes `.env` and `.env.*` (while allowing
`.env.example`, `.env.sample`, and `.env.template`), common private-key IDs,
`*.pem`, `*.key`, `*.p12`, `*.pfx`, and common credentials, service-account,
and secrets JSON/YAML filenames. Set `report.includeSensitiveFiles` to `true`
only to bypass this baseline. The configured `exclude` list always still applies
and should cover generated content plus project-specific secret-bearing paths.
This protection is path-based: it does not inspect file contents, commit
messages, or branch names for secrets. Copying secret content into a path whose
name is not sensitive can therefore bypass the baseline and requires an
explicit project-specific exclude.

Relative `roots[].path` and `outputDir` values are resolved from the process's
current working directory.

`scrum` is optional. Only the `/scrum` skill reads it, and `--doctor` does not
validate it; when the block is missing the skill stops with a hint instead of
guessing. Standup summaries are work records rather than learning material, so
`scrum.outputDir` normally points outside `reports/`.

## When Reports Are Generated

A project report is generated when at least one of these is true:

- the repository has one or more commits by a configured author email
- current changes are enabled and the repository has staged changes
- current changes are enabled and the repository has unstaged changes
- current changes are enabled and the repository has untracked files

Today's report includes the current working tree by default. A historical
`--date` report includes only activity from that date, because today's staged,
unstaged, and untracked files do not describe the historical state. Add
`--include-current-changes` only when you intentionally want the current working
tree included in a historical report.

Commit dates use the committer date in the machine's local timezone for
`--date` filtering, displayed commit time, and missed-day aggregation. Commits
are newest-first. Multiple `authorEmails` are combined as an OR filter and each
commit is included only once.

When current changes are enabled, staged and unstaged changes include both file
lists and diffs by default. Untracked files are listed without diffs.
Each diff block retains at most `report.maxDiffLines` lines and
`report.maxDiffBytes` raw bytes. Reaching either limit terminates that Git diff
and records that the remaining output was omitted. `0` disables only the
corresponding limit.

If current working tree diffs are too large or sensitive, disable them:

```json
{
  "report": {
    "includeUncommittedDiff": false
  }
}
```

Generated report metadata uses the repository-relative path instead of the local
absolute path, and does not render configured author email addresses. Diffs can
still contain source code, credentials, personal data, or machine-specific text,
so inspect reports before sharing them and maintain appropriate `exclude`
patterns.

Re-running a date overwrites that date's generated file for the same root and
repository only when the existing regular file still has the matching dated
header and full identity marker in its first two lines. Keep those two lines
intact when editing a generated report. A foreign file, symbolic link, or
special file present when the deterministic target is validated is refused
instead of replaced.
Concurrent Daily Code Learn writers cooperate through a directory lock. As
with other owner-writable files, unrelated processes running as the same OS
user are inside the filesystem trust boundary and must not mutate the target
during generation.
The date-specific report directory itself must also be a real directory, not a
symbolic link, for generation, missed-day detection, and notification. Report
generation also refuses a date directory not owned by the current user or
writable by its group or other users.
The command does not delete other project reports or analysis files. Legacy
generated project-only files at `reports/{date}/{project}.md` are not migrated
or deleted and still count when checking for a previously generated day. New
files use the collision-resistant readable identity and hash. Each eligible
report is atomically replaced with owner-only `0600` permissions, and newly
created date directories use `0700`, on supported filesystems. If publication
is interrupted after replacement may have started, the prior inode is retained
as a hidden recovery file and the next run stops rather than accumulating or
silently deleting recovery data.

## Missed Report Days

Use `--check-missed` to find dates where you committed code but did not generate a project report.

```bash
python3 generate.py --check-missed --days 14
```

Behavior:

- The check is date-based, not project-based.
- It uses each commit's local-timezone committer date and the configured author-email OR filter.
- Today is excluded by default because you may not have written the report yet.
- A date counts as reported when a `.md` file in `reports/{date}` has the exact-date project header plus either the current full identity marker or the basic-info structure written by legacy reports. This recognizes both formats without treating a date-shaped note as a report.
- Analysis files do not count unless they deliberately imitate one of those generated report structures.
- The CLI shows the latest 10 missed dates by number.
- Dates in the checked range that are not shown in the latest 10 can be selected by typing `YYYY-MM-DD`.
- Press `Enter`, `q`, or `quit` to cancel without generating a report.

## Diagnostics and Exit Codes

Git failures are reported with the affected root-relative repository path. A
fetch, discovery, or collection failure is not treated as normal "no activity":
the run is marked incomplete and exits non-zero. Reports collected successfully
from other repositories are still written. Use `--verbose` for the additional
low-level Git diagnostic log.

| Exit code | Meaning |
| --- | --- |
| `0` | Command completed, including no matching work or a cancelled missed-day selection when its scan was complete |
| `1` | Configuration, repository collection, report writing, or notification failed or was incomplete |
| `2` | CLI usage rejected by the argument parser |

## LLM Analysis Workflow

Generated reports include Git diffs, so you can ask an LLM to turn them into learning notes.

### Skills

The repository ships skills for Claude Code (`.claude/skills/`) and Codex
(`.agents/skills/`, agentskills.io layout). Open a session in the project root and
invoke them by name. Codex uses a `$` prefix (`$analyze`, `$dig`, and so on).

| Skill | What it does | Writes |
| --- | --- | --- |
| `/analyze [date]` | Reads every report for one day and writes a learning analysis following `prompts/analyze.md`. Sends the result through Telegram when enabled. | `reports/{date}/claude-analysis.md` from Claude Code, `codex-analysis.md` from Codex |
| `/dig <project> [date]` | Opens a follow-up conversation about one project's diff for that day. It first recalls what you did not know from earlier `/dig` sessions on the same project, reads the repository's source when the diff alone cannot answer a question, and cross-references the project's rows across every past analysis. Without arguments it lists the projects that have a report for the day. | Nothing until you run `/publish` |
| `/publish [project]` | Closes a `/dig` conversation by recording what you did not know as question, one-line answer, and takeaway. It is not a transcript, and it does not invent entries when you asked nothing. | `reports/dig/{root--repo}/{date}.md`, appended when the file already exists |
| `/scrum` | Summarizes the last working day plus this morning for the `scrum.root` workspace, grouped by project, for a morning standup. Runs `generate.py --check-missed` and `generate.py` first so the reports are current. | `{scrum.outputDir}/{date}.md`, overwritten on the same day |

`/dig` and `/publish` keep their output under `reports/dig/`, beside the dated
report directories. `--check-missed`, `--notify`, and `/analyze` only look inside
`reports/{date}/`, so those files are never mistaken for reports or sent anywhere.

`/scrum` is a work report, not a learning note. It copies ticket IDs and `#time`
values from commit titles verbatim, condenses long commit comments to one
sentence, drops merge and version-bump commits, and omits a repository that had
only those. Set `scrum.root` and `scrum.outputDir` in `config/profiles.json` first.

### Without skills

The analysis prompt template is available at:

```text
prompts/analyze.md
```

Example Claude workflow:

```bash
claude
```

Then ask:

```text
Analyze the reports in reports/2026-03-12 using prompts/analyze.md.
Save the result as reports/2026-03-12/claude-analysis.md.
```

Example Codex workflow:

```bash
codex
```

Then ask:

```text
Analyze the reports in reports/2026-03-12 using prompts/analyze.md.
Save the result as reports/2026-03-12/codex-analysis.md.
```

You can edit `prompts/analyze.md` to match your own learning goals.

## Telegram Notifications

Telegram is optional. Daily Code Learn does not send messages by default.

Create `.env`:

```bash
cp .env.example .env
chmod 600 .env
```

Set these values:

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Enable Telegram in `config/profiles.json`:

```json
{
  "telegram": {
    "enabled": true
  }
}
```

Credentials are read only from `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
Credential-looking values persisted in `profiles.json` are ignored.
The CLI refuses a symbolic-link, non-regular, foreign-owned, or group/other
accessible `.env` file.

Send an analysis file:

```bash
python3 lib/notifier.py reports/2026-04-09/codex-analysis.md 2026-04-09
```

Generate reports and send them immediately:

```bash
python3 generate.py --notify
```

`--notify` sends only report files written by the current run. It does not
re-send legacy, stale, or analysis Markdown already present in the date folder.
Before conversion, it verifies that each current-run artifact still has the
same directory identity, file identity, and SHA-256 content recorded at write
time; a replaced or modified artifact is refused.
Because notification is explicitly requested, the command exits non-zero when
Telegram is disabled, credentials are missing, or any delivery fails.

The direct `lib/notifier.py` command accepts only a regular, non-symlink UTF-8
file no larger than 8 MiB. It does not reapply the report `exclude` or
sensitive-path filters or scan the content for secrets, so review the complete
file before sending. The internal report identity marker is the only
generated-report metadata omitted from Telegram messages. A conversion that
would require more than 100 messages is rejected before any part is delivered.

Telegram formatting:

- Markdown is converted to Telegram-compatible HTML.
- Messages are split with HTML wrapper overhead included, so every transmitted chunk stays within Telegram's 4096-character limit.
- Non-BMP characters are counted conservatively as UTF-16 code units when enforcing that limit.
- Display control characters in content, filenames, and dates are rendered as visible escapes.
- Local `.md` files remain unchanged.

## Troubleshooting

### Config file is missing

```bash
python3 generate.py --init
```

Then edit `config/profiles.json` and set `roots[].path`, `authorNames`, and `authorEmails`.

### No reports are generated

```bash
python3 generate.py --doctor
```

Check that:

- `roots[].path` points to the parent directory that contains your Git repositories
- `authorEmails` matches the email shown in `git log`
- the target date has matching commits
- for today's report, the repository has staged, unstaged, or untracked changes
- for a historical date where current changes are intentional, `--include-current-changes` is present

### Diffs are too long or sensitive

Adjust diff settings in `config/profiles.json`:

```json
{
  "report": {
    "includeUncommittedDiff": false,
    "maxDiffLines": 600,
    "maxDiffBytes": 1048576
  }
}
```

### A pre-existing report directory is rejected

Generation requires `reports/{date}` to be owned by the current user and not
writable by group or other users. After reviewing the directory ownership and
contents, remove broader permissions if an older run created it under a
permissive umask:

```bash
chmod 700 reports/2026-03-12
```

### Report publication or recovery is refused

Safe publication requires same-directory hard links, atomic replacement, and
directory `fsync`. Choose another `outputDir` on a compatible filesystem if
those operations are unsupported (some network, removable, or userspace
filesystems may differ).

An interrupted write may leave a hidden `.report-*.tmp` or
`.previous-report-*.tmp` recovery file. The next run stops with its path.
Compare that file with the deterministic `.md` target, preserve the version you
need, and remove only the reviewed recovery artifact before retrying.

### Telegram does not send messages

- Check `.env` for `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
- Run `chmod 600 .env`; broader permissions and symbolic links are refused.
- Check that `telegram.enabled` is `true` in `config/profiles.json`.
- Run `python3 generate.py --doctor` to find missing environment variables.

## Project Structure

```text
daily-code-learn/
  generate.py                 # CLI entry point
  lib/
    config.py                 # config loading and CLI argument parsing
    scanner.py                # depth-bounded repository and worktree discovery
    git_commands.py           # Git command wrappers
    colors.py                 # ANSI terminal color helpers
    collector.py              # report data collection
    parallel.py               # shared concurrent repository runner
    progress.py               # thread-safe terminal progress display
    missed_days.py            # missed report day detection
    renderer.py               # Markdown rendering and file writing
    notifier.py               # Telegram notification sending
  .claude/skills/             # Claude Code skills: analyze, dig, publish, scrum
  .agents/skills/             # Codex skills; dig, publish, scrum link to .claude/skills/
  prompts/
    analyze.md                # LLM analysis prompt template
  config/
    profiles.example.json     # example config
    profiles.json             # local config, ignored by Git
  .env.example                # environment variable template
  .env                        # local secrets, ignored by Git
  reports/                    # generated reports, ignored by Git
    {date}/                   # per-day project reports and LLM analyses
    dig/                      # /publish output, one folder per project
  tests/                      # unit and integration-style regression tests
  .github/workflows/ci.yml    # Linux Python matrix and macOS smoke test
```

## Release

Current version:

```bash
python3 generate.py --version
```

Release checklist:

- `python3 -m unittest discover -v` passes
- `CHANGELOG.md` includes the version changes
- Git tags use the `vX.Y.Z` format
- GitHub Releases include usage notes, major changes, and known limitations

## License

MIT
