# Security Policy

## Supported Versions

The latest GitHub release is the supported version.

## Reporting a Vulnerability

Use **Report a vulnerability** in this repository's GitHub **Security** tab to
open a private security advisory. Include the affected version, impact, and a
minimal reproduction that does not expose unrelated private data.

Do not report vulnerabilities in a public issue, discussion, pull request, or
commit. If private advisory reporting is unavailable, contact the maintainer
through a private contact method listed on their GitHub profile and ask for a
secure reporting channel. Share only a high-level description until a private
channel is confirmed; never send tokens, credentials, or private source code in
the initial message.

## Data Safety Notes

Daily Code Learn reads local Git repositories and can include code diffs in generated Markdown reports. Treat `reports/` as potentially sensitive.

- Do not commit `.env`, `config/profiles.json`, or generated reports.
- Generated reports are atomically replaced with owner-only file permissions, and newly created date directories are owner-only on supported systems; keep pre-existing parent directories private as well. Generation refuses date directories not owned by the current user or writable by group/others; after verifying ownership and contents, older permissive directories can be restricted with `chmod 700 reports/YYYY-MM-DD`. Existing deterministic targets are backed up by inode, revalidated, and replaced only when their dated header and full identity marker match; foreign files present at validation, symbolic links, special files, and symbolic-link date directories are refused.
- Safe publication requires the `outputDir` filesystem to support same-directory hard links, atomic replacement, and directory `fsync`. An interrupted publication can retain a hidden recovery file; review it against the `.md` target and preserve the desired version before removing that artifact and retrying.
- Directory locking serializes cooperating Daily Code Learn writers. Processes running under the same OS account can already modify owner-writable files and are therefore inside the trust boundary; do not run untrusted concurrent processes under that account against the report directory.
- Keep `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` out of public logs and screenshots. Runtime credentials are loaded only from environment variables; credential-looking fields in `profiles.json` are ignored. Keep `.env` at `0600`; the CLI refuses symbolic-link, non-regular, foreign-owned, or group/other-accessible environment files.
- Keep `report.includeSensitiveFiles` at its default `false` unless you have reviewed and intentionally accepted the additional exposure.
- Treat the built-in sensitive-file filter as a path-based baseline, not content or secret scanning.
- Review and extend `exclude` patterns for project-specific credential, key, and environment files.
- Set `report.includeUncommittedDiff` to `false` if current working tree diffs may contain sensitive data.
- Review generated Markdown before sending it to an LLM, Telegram, or another third party.
- `--notify` binds delivery to the directory inode, file inode, and SHA-256 content produced by the current run, and refuses an artifact changed between writing and conversion.
- The direct notifier accepts only a regular, non-symlink UTF-8 file up to 8 MiB and rejects conversions over 100 messages before partial delivery, but it sends the converted content (apart from the internal report identity marker) without rerunning report path filters or secret scanning. Review direct-notifier input independently before sending it.
