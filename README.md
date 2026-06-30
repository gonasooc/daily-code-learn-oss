# Daily Code Learn

<p align="center">
  <img src="docs/thumbnail.svg" alt="Daily Code Learn" width="100%">
</p>

[Korean README](docs/README.ko.md)

Daily Code Learn is a zero-dependency Python CLI that turns your daily Git activity into Markdown learning reports.

Run one terminal command before you finish work, and it scans your configured workspaces for repositories with activity, then writes one Markdown report per project. The generated reports are designed to be sent to Claude, Codex, or another LLM for learning-oriented analysis.

## Features

- Uses only the Python standard library. No runtime dependencies.
- Runs with the default Python 3 installation on macOS and Linux.
- Scans Git repositories under one or more configured workspace roots.
- Runs `git fetch` before collecting commits, so commits pushed from another machine can be detected without running `git pull`.
- Captures commit history, staged changes, unstaged changes, and untracked file lists.
- Includes configurable diffs for committed and uncommitted changes.
- Detects missed report days with `--check-missed`.
- Can send generated analysis Markdown to Telegram when enabled.

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
reports/{date}/{project-name}.md
```

## Commands

```bash
# Print the current version.
python3 generate.py --version

# Create config/profiles.json from the example config.
python3 generate.py --init

# Check config, workspace paths, author values, and Telegram env vars.
python3 generate.py --doctor

# Generate reports for today.
python3 generate.py

# Generate reports for a specific date.
python3 generate.py --date 2026-03-12

# Generate reports and send them through Telegram if Telegram is enabled.
python3 generate.py --notify

# Find recent work days that do not have reports yet.
python3 generate.py --check-missed

# Check the last 14 days instead of the default 30 days.
python3 generate.py --check-missed --days 14
```

`--check-missed` does more than list missing days. After you select a missed day, it immediately generates reports for that date.

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
      "authorNames": ["My Name"],
      "authorEmails": ["my@email.com"]
    }
  ],
  "outputDir": "./reports",
  "report": {
    "includeUncommittedDiff": true,
    "maxDiffLines": 1200
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
  }
}
```

`reports/` and `config/profiles.json` are local files and are ignored by Git.

Run the setup checker after editing config:

```bash
python3 generate.py --doctor
```

`--doctor` checks:

- whether `config/profiles.json` exists and can be parsed
- whether each `roots[].path` exists
- how many Git repositories are found under each root
- whether example author values are still present
- whether Telegram environment variables are present when Telegram is enabled

| Field | Description |
| --- | --- |
| `roots[].name` | Workspace label shown in terminal output |
| `roots[].path` | Parent directory that contains Git repositories |
| `roots[].authorNames` | Git author names for report metadata |
| `roots[].authorEmails` | Git author emails used to filter commits |
| `outputDir` | Directory where reports are written |
| `report.includeUncommittedDiff` | Whether staged and unstaged diffs are included. Default: `true` |
| `report.maxDiffLines` | Maximum number of diff lines per block. Default: `1200` |
| `exclude` | File or directory patterns excluded from diff output |
| `telegram.enabled` | Whether Telegram sending is enabled. Default: `false` |

## When Reports Are Generated

A project report is generated when at least one of these is true for the selected date:

- the repository has one or more commits by a configured author email
- the repository has staged changes
- the repository has unstaged changes
- the repository has untracked files

By default, staged and unstaged changes include both file lists and diffs. Untracked files are listed without diffs.

If current working tree diffs are too large or sensitive, disable them:

```json
{
  "report": {
    "includeUncommittedDiff": false
  }
}
```

## Missed Report Days

Use `--check-missed` to find dates where you committed code but did not generate a project report.

```bash
python3 generate.py --check-missed --days 14
```

Behavior:

- The check is date-based, not project-based.
- It uses commits by configured author emails.
- Today is excluded by default because you may not have written the report yet.
- A date counts as reported when `reports/{date}` contains at least one project `.md` file.
- Analysis-only files such as `analysis.md`, `codex-analysis.md`, `claude-analysis.md`, and `*-analysis.md` do not count as project reports.
- The CLI shows the latest 10 missed dates by number.
- Older dates can be selected by typing `YYYY-MM-DD`.
- Press `Enter`, `q`, or `quit` to cancel without generating a report.

## LLM Analysis Workflow

Generated reports include Git diffs, so you can ask an LLM to turn them into learning notes.

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

Send an analysis file:

```bash
python3 lib/notifier.py reports/2026-04-09/codex-analysis.md 2026-04-09
```

Generate reports and send them immediately:

```bash
python3 generate.py --notify
```

Telegram formatting:

- Markdown is converted to Telegram-compatible HTML.
- Messages longer than 4096 characters are split by line.
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
- the target date has commits, staged changes, unstaged changes, or untracked files

### Diffs are too long or sensitive

Adjust diff settings in `config/profiles.json`:

```json
{
  "report": {
    "includeUncommittedDiff": false,
    "maxDiffLines": 600
  }
}
```

### Telegram does not send messages

- Check `.env` for `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
- Check that `telegram.enabled` is `true` in `config/profiles.json`.
- Run `python3 generate.py --doctor` to find missing environment variables.

## Project Structure

```text
daily-code-learn/
  generate.py                 # CLI entry point
  lib/
    config.py                 # config loading and CLI argument parsing
    scanner.py                # Git repository discovery under workspace roots
    git_commands.py           # Git command wrappers
    colors.py                 # ANSI terminal color helpers
    collector.py              # report data collection
    missed_days.py            # missed report day detection
    renderer.py               # Markdown rendering and file writing
    notifier.py               # Telegram notification sending
  prompts/
    analyze.md                # LLM analysis prompt template
  config/
    profiles.example.json     # example config
    profiles.json             # local config, ignored by Git
  .env.example                # environment variable template
  .env                        # local secrets, ignored by Git
  reports/                    # generated reports, ignored by Git
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
