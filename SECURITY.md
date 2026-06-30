# Security Policy

## Supported Versions

The latest GitHub release is the supported version.

## Reporting a Vulnerability

Please open a private security advisory on GitHub if possible. If that is not available, open an issue with minimal reproduction details and avoid posting secrets, tokens, or private code.

## Data Safety Notes

Daily Code Learn reads local Git repositories and can include code diffs in generated Markdown reports. Treat `reports/` as potentially sensitive.

- Do not commit `.env`, `config/profiles.json`, or generated reports.
- Keep `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` out of public logs and screenshots.
- Set `report.includeUncommittedDiff` to `false` if current working tree diffs may contain sensitive data.
