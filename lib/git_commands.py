"""Git command helpers used by report collection."""

import fnmatch
import logging
import os
import re
import shlex
import subprocess
import tempfile
import threading

from lib.colors import safe_terminal_text

logger = logging.getLogger(__name__)

GIT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_DIFF_BYTES = 2 * 1024 * 1024
DIFF_READ_CHUNK_SIZE = 64 * 1024
MAX_PATHS_PER_DIFF_COMMAND = 256
MAX_PATHSPEC_BYTES_PER_DIFF_COMMAND = 32 * 1024


class GitCommandError(RuntimeError):
    """A sanitized, user-displayable Git command failure."""

    def __init__(self, repo_path, command, detail):
        self.repo_path = repo_path
        self.command = command
        self.detail = detail
        super().__init__(f"git {command} 실패: {detail}")


def _escape_surrogate_bytes(value):
    """Render undecodable process bytes without losing their byte identity."""
    escaped = []
    for character in str(value):
        codepoint = ord(character)
        if 0xDC80 <= codepoint <= 0xDCFF:
            escaped.append(f"\\x{codepoint - 0xDC00:02x}")
        else:
            escaped.append(character)
    return "".join(escaped)


def _sanitize_error(stderr):
    """Keep diagnostics useful without echoing credentials in remote URLs."""
    value = _escape_surrogate_bytes(stderr or "알 수 없는 오류")
    value = value.strip().replace("\x00", "")
    value = re.sub(
        r"([A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@",
        r"\1***@",
        value,
    )
    value = re.sub(
        r"(?i)([?&](?:access_token|api_key|key|password|passwd|secret|token)=)[^&\s]+",
        r"\1***",
        value,
    )
    if len(value) > 500:
        value = value[:497] + "..."
    return safe_terminal_text(value)


def _git_command(repo_path, args):
    return [
        "git",
        "--literal-pathspecs",
        "-c",
        "core.quotePath=false",
        "-C",
        repo_path,
        *args,
    ]


def _git_env():
    env = os.environ.copy()
    # shortstat parsing and user-facing diagnostics must not depend on locale.
    env["LC_ALL"] = "C"
    # A daily report command must fail predictably instead of blocking for
    # interactive credentials in one of many repositories.
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run_git(repo_path, args):
    """Run Git and return stdout, raising a sanitized error on failure."""
    command_name = args[0] if args else "command"
    try:
        result = subprocess.run(
            _git_command(repo_path, args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            timeout=GIT_TIMEOUT_SECONDS,
            env=_git_env(),
        )
    except subprocess.TimeoutExpired as e:
        raise GitCommandError(
            repo_path,
            command_name,
            f"{GIT_TIMEOUT_SECONDS}초 시간 제한 초과",
        ) from e
    except (OSError, UnicodeError) as e:
        raise GitCommandError(
            repo_path,
            command_name,
            _sanitize_error(str(e)),
        ) from e

    if result.returncode != 0:
        detail = _sanitize_error(result.stderr)
        logger.debug(
            "git %s failed in %s: %s",
            command_name,
            safe_terminal_text(repo_path),
            detail,
        )
        raise GitCommandError(repo_path, command_name, detail)

    return result.stdout.rstrip("\n")


def _normalize_path(path):
    normalized = str(path)
    if os.sep == "\\":
        normalized = normalized.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _matches_exclude(path, pattern):
    """Match documented glob/segment excludes without substring overmatching."""
    normalized_path = _normalize_path(path)
    normalized_pattern = str(pattern).strip()
    if os.sep == "\\":
        normalized_pattern = normalized_pattern.replace("\\", "/")
    if not normalized_pattern:
        return False

    if "/" not in normalized_pattern:
        segments = normalized_path.split("/")
        return any(fnmatch.fnmatchcase(segment, normalized_pattern) for segment in segments)

    return (
        fnmatch.fnmatchcase(normalized_path, normalized_pattern)
        or fnmatch.fnmatchcase(normalized_path, f"*/{normalized_pattern}")
    )


def _is_sensitive_path(path):
    """Return whether a path is a likely secret-bearing file."""
    basename = _normalize_path(path).rsplit("/", 1)[-1].lower()
    safe_env_templates = {".env.example", ".env.sample", ".env.template"}
    private_key_names = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}
    sensitive_names = {
        "credentials.json",
        "credentials.yaml",
        "credentials.yml",
        "service-account.json",
        "service-account.yaml",
        "service-account.yml",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
    }

    if basename == ".env":
        return True
    if basename.startswith(".env.") and basename not in safe_env_templates:
        return True
    if basename in private_key_names or basename in sensitive_names:
        return True
    return basename.endswith((".pem", ".key", ".p12", ".pfx"))


def _is_excluded(path, excludes, include_sensitive_files=False):
    if not include_sensitive_files and _is_sensitive_path(path):
        return True
    return any(_matches_exclude(path, pattern) for pattern in excludes)


def _filter_excludes(files, excludes, include_sensitive_files=False):
    return [
        path
        for path in files
        if not _is_excluded(path, excludes, include_sensitive_files)
    ]


def _diff_paths_from_header(line):
    """Extract a/b paths from ordinary and Git-quoted diff headers."""
    match = re.match(r"^diff --git a/(.*?) b/(.*)$", line)
    if match:
        return [match.group(1), match.group(2)]

    try:
        parts = shlex.split(line)
    except ValueError:
        parts = line.split()

    paths = []
    for value in parts[2:4]:
        if value.startswith(("a/", "b/")):
            paths.append(value[2:])
    return paths


def _filter_diff_excludes(output, excludes, include_sensitive_files=False):
    """Remove excluded file blocks from an already captured diff."""
    if not output:
        return ""

    filtered = []
    skip_file = False
    for line in output.split("\n"):
        if line.startswith("diff --git"):
            paths = _diff_paths_from_header(line)
            skip_file = any(
                _is_excluded(path, excludes, include_sensitive_files)
                for path in paths
            )
        if not skip_file:
            filtered.append(line)
    return "\n".join(filtered).strip()


def _run_git_diff(
    repo_path,
    args,
    excludes,
    max_lines=0,
    include_sensitive_files=False,
    max_bytes=DEFAULT_MAX_DIFF_BYTES,
    marker_max_lines=None,
    marker_max_bytes=None,
):
    """Stream a diff within line/byte limits after path filtering."""
    command_name = args[0] if args else "diff"
    timed_out = threading.Event()
    stopped_reason = None

    try:
        with tempfile.TemporaryFile(
            mode="w+",
            encoding="utf-8",
            errors="surrogateescape",
        ) as stderr_file:
            process = subprocess.Popen(
                _git_command(repo_path, args),
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                text=True,
                encoding="utf-8",
                errors="surrogateescape",
                env=_git_env(),
            )

            def _terminate_on_timeout():
                timed_out.set()
                try:
                    process.kill()
                except OSError:
                    pass

            timer = threading.Timer(GIT_TIMEOUT_SECONDS, _terminate_on_timeout)
            timer.daemon = True
            timer.start()

            retained = []
            included_line_count = 0
            included_byte_count = 0
            skip_file = False
            at_line_start = True
            try:
                assert process.stdout is not None
                while True:
                    fragment = process.stdout.readline(DIFF_READ_CHUNK_SIZE)
                    if not fragment:
                        break

                    ends_line = fragment.endswith("\n")
                    if at_line_start and fragment.startswith("diff --git"):
                        paths = _diff_paths_from_header(fragment.rstrip("\n"))
                        skip_file = any(
                            _is_excluded(path, excludes, include_sensitive_files)
                            for path in paths
                        )
                    if skip_file:
                        at_line_start = ends_line
                        continue

                    if at_line_start:
                        if max_lines > 0 and included_line_count >= max_lines:
                            stopped_reason = "lines"
                            try:
                                process.terminate()
                            except OSError:
                                pass
                            break
                        included_line_count += 1

                    fragment_bytes = fragment.encode(
                        "utf-8",
                        errors="surrogateescape",
                    )
                    if (
                        max_bytes > 0
                        and included_byte_count + len(fragment_bytes) > max_bytes
                    ):
                        remaining_bytes = max_bytes - included_byte_count
                        if remaining_bytes > 0:
                            retained.append(
                                fragment_bytes[:remaining_bytes].decode(
                                    "utf-8",
                                    errors="surrogateescape",
                                )
                            )
                            included_byte_count += remaining_bytes
                        stopped_reason = "bytes"
                        try:
                            process.terminate()
                        except OSError:
                            pass
                        break
                    retained.append(fragment)
                    included_byte_count += len(fragment_bytes)
                    at_line_start = ends_line
            finally:
                if process.stdout is not None:
                    process.stdout.close()
                return_code = process.wait()
                timer.cancel()

            stderr_file.seek(0)
            stderr = stderr_file.read()
    except (OSError, UnicodeError) as e:
        raise GitCommandError(
            repo_path,
            command_name,
            _sanitize_error(str(e)),
        ) from e

    if timed_out.is_set() and return_code != 0 and stopped_reason is None:
        raise GitCommandError(
            repo_path,
            command_name,
            f"{GIT_TIMEOUT_SECONDS}초 시간 제한 초과",
        )
    if return_code != 0 and stopped_reason is None:
        raise GitCommandError(repo_path, command_name, _sanitize_error(stderr))

    truncated = stopped_reason is not None
    omitted = None if truncated else 0
    output = _escape_surrogate_bytes("".join(retained).strip())
    displayed_max_lines = (
        max_lines if marker_max_lines is None else marker_max_lines
    )
    displayed_max_bytes = (
        max_bytes if marker_max_bytes is None else marker_max_bytes
    )
    if stopped_reason == "lines":
        marker = f"... 최대 {displayed_max_lines}줄 이후 diff 생략 ..."
    elif stopped_reason == "bytes":
        marker = f"... 최대 {displayed_max_bytes}바이트 이후 diff 생략 ..."
    else:
        marker = ""
    if marker:
        output = f"{output}\n{marker}" if output else marker
    return output, truncated, omitted


def _parse_name_status_z(output):
    """Parse `--name-status -z` into path groups per logical change."""
    tokens = [token for token in output.split("\0") if token]
    changes = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        index += 1
        path_count = 2 if status.startswith(("R", "C")) else 1
        if index + path_count > len(tokens):
            break
        changes.append(tokens[index:index + path_count])
        index += path_count
    return changes


def _safe_changed_path_groups(
    repo_path,
    metadata_args,
    excludes,
    include_sensitive_files,
):
    """Return path groups for changes whose old/new paths are all allowed."""
    if include_sensitive_files and not excludes:
        return None

    output = _run_git(repo_path, metadata_args)
    safe_groups = []
    for paths in _parse_name_status_z(output):
        if any(
            _is_excluded(path, excludes, include_sensitive_files)
            for path in paths
        ):
            continue
        safe_groups.append(paths)
    return safe_groups


def _safe_changed_paths(
    repo_path,
    metadata_args,
    excludes,
    include_sensitive_files,
):
    """Return de-duplicated safe paths for compatibility with older callers."""
    groups = _safe_changed_path_groups(
        repo_path,
        metadata_args,
        excludes,
        include_sensitive_files,
    )
    if groups is None:
        return None

    safe_paths = []
    seen_paths = set()
    for group in groups:
        for path in group:
            if path not in seen_paths:
                seen_paths.add(path)
                safe_paths.append(path)
    return safe_paths


def _chunk_path_groups(path_groups):
    """Bound each pathspec argv while keeping rename/copy pairs together."""
    chunk = []
    chunk_bytes = 0
    for group in path_groups:
        group_bytes = sum(len(os.fsencode(path)) + 1 for path in group)
        if chunk and (
            len(chunk) + len(group) > MAX_PATHS_PER_DIFF_COMMAND
            or chunk_bytes + group_bytes > MAX_PATHSPEC_BYTES_PER_DIFF_COMMAND
        ):
            yield chunk
            chunk = []
            chunk_bytes = 0
        chunk.extend(group)
        chunk_bytes += group_bytes
    if chunk:
        yield chunk


def _limit_marker(max_lines, max_bytes, reason):
    if reason == "lines":
        return f"... 최대 {max_lines}줄 이후 diff 생략 ..."
    return f"... 최대 {max_bytes}바이트 이후 diff 생략 ..."


def _limited_filtered_diff(
    repo_path,
    diff_args,
    metadata_args,
    excludes,
    max_lines,
    include_sensitive_files,
    max_bytes=DEFAULT_MAX_DIFF_BYTES,
):
    safe_groups = _safe_changed_path_groups(
        repo_path,
        metadata_args,
        excludes,
        include_sensitive_files,
    )
    if safe_groups == []:
        return "", False, 0

    path_chunks = [None] if safe_groups is None else list(
        _chunk_path_groups(safe_groups)
    )
    parts = []
    used_lines = 0
    used_bytes = 0

    for chunk_index, safe_paths in enumerate(path_chunks):
        separator_bytes = 1 if parts else 0
        if max_lines > 0 and used_lines >= max_lines:
            parts.append(_limit_marker(max_lines, max_bytes, "lines"))
            return "\n".join(parts), True, None
        if max_bytes > 0 and used_bytes + separator_bytes >= max_bytes:
            parts.append(_limit_marker(max_lines, max_bytes, "bytes"))
            return "\n".join(parts), True, None

        chunk_args = diff_args
        if safe_paths is not None:
            chunk_args = [*diff_args, "--", *safe_paths]

        remaining_lines = max_lines - used_lines if max_lines > 0 else 0
        remaining_bytes = (
            max_bytes - used_bytes - separator_bytes
            if max_bytes > 0
            else 0
        )

        # Paths were filtered from NUL-delimited metadata, so header parsing is
        # no longer part of the security boundary for this streamed patch.
        diff, truncated, omitted = _run_git_diff(
            repo_path,
            chunk_args,
            [],
            remaining_lines,
            include_sensitive_files=True,
            max_bytes=remaining_bytes,
            marker_max_lines=max_lines,
            marker_max_bytes=max_bytes,
        )
        if diff:
            parts.append(diff)
            if not truncated:
                used_lines += diff.count("\n") + 1
                used_bytes += separator_bytes + len(diff.encode("utf-8"))
        if truncated:
            return "\n".join(parts), True, omitted

        has_more_chunks = chunk_index + 1 < len(path_chunks)
        if has_more_chunks and max_lines > 0 and used_lines >= max_lines:
            parts.append(_limit_marker(max_lines, max_bytes, "lines"))
            return "\n".join(parts), True, None
        if has_more_chunks and max_bytes > 0 and used_bytes >= max_bytes:
            parts.append(_limit_marker(max_lines, max_bytes, "bytes"))
            return "\n".join(parts), True, None

    return "\n".join(parts), False, 0


def fetch(repo_path):
    """Fetch remote refs without changing the working tree."""
    _run_git(repo_path, ["fetch", "--quiet"])


def validate_worktree(repo_path):
    """Raise when a discovered `.git` marker is not a usable worktree."""
    result = _run_git(repo_path, ["rev-parse", "--is-inside-work-tree"])
    if result.strip() != "true":
        raise GitCommandError(repo_path, "rev-parse", "worktree 저장소가 아닙니다.")


def get_current_branch(repo_path):
    branch = _run_git(repo_path, ["branch", "--show-current"])
    return branch or "(detached HEAD)"


def get_commits_by_author(repo_path, author_emails, date):
    """Return commits for a local-calendar committer date, newest first."""
    if not author_emails:
        return []

    allowed_emails = {email.strip().casefold() for email in author_emails}
    output = _run_git(repo_path, [
        "log",
        "--all",
        f"--since-as-filter={date} 00:00:00",
        f"--until={date} 23:59:59",
        "--pretty=format:%H%x00%cd%x00%ct%x00%ae%x00%s",
        "--date=format-local:%Y-%m-%d %H:%M:%S %z",
        "--shortstat",
    ])
    if not output:
        return []

    commits = []
    lines = output.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue

        parts = line.split("\0", 4)
        if len(parts) < 5:
            index += 1
            continue

        (
            hash_value,
            date_string,
            committer_epoch,
            author_email,
            subject,
        ) = parts
        stat_line = ""
        if (
            index + 1 < len(lines)
            and lines[index + 1].strip()
            and "\0" not in lines[index + 1]
        ):
            stat_line = lines[index + 1].strip()
            index += 2
        else:
            index += 1

        if not date_string.startswith(f"{date} "):
            continue
        if author_email.strip().casefold() not in allowed_emails:
            continue
        try:
            sort_epoch = int(committer_epoch)
        except ValueError:
            continue

        files_changed, insertions, deletions = _parse_shortstat(stat_line)
        commits.append({
            "hash": hash_value,
            "date": date_string,
            "subject": subject,
            "files_changed": files_changed,
            "insertions": insertions,
            "deletions": deletions,
            "_sort_epoch": sort_epoch,
        })

    commits.sort(
        key=lambda commit: (commit["_sort_epoch"], commit["hash"]),
        reverse=True,
    )
    for commit in commits:
        del commit["_sort_epoch"]
    return commits


def get_commit_dates_by_author(repo_path, author_emails, start_date, end_date):
    """Count commits by local-calendar committer date."""
    if not author_emails:
        return {}

    allowed_emails = {email.strip().casefold() for email in author_emails}
    output = _run_git(repo_path, [
        "log",
        "--all",
        f"--since-as-filter={start_date} 00:00:00",
        f"--until={end_date} 23:59:59",
        "--pretty=format:%H%x00%cd%x00%ae",
        "--date=format-local:%Y-%m-%d",
    ])
    if not output:
        return {}

    commit_dates = {}
    seen_hashes = set()
    for line in output.split("\n"):
        parts = line.split("\0", 2)
        if len(parts) < 3:
            continue
        hash_value, date_string, author_email = parts
        if not start_date <= date_string <= end_date:
            continue
        if author_email.strip().casefold() not in allowed_emails:
            continue
        if hash_value in seen_hashes:
            continue
        seen_hashes.add(hash_value)
        commit_dates[date_string] = commit_dates.get(date_string, 0) + 1
    return commit_dates


def _parse_shortstat(stat_string):
    files_changed = 0
    insertions = 0
    deletions = 0
    if not stat_string:
        return files_changed, insertions, deletions

    match = re.search(r"(\d+) file", stat_string)
    if match:
        files_changed = int(match.group(1))
    match = re.search(r"(\d+) insertion", stat_string)
    if match:
        insertions = int(match.group(1))
    match = re.search(r"(\d+) deletion", stat_string)
    if match:
        deletions = int(match.group(1))
    return files_changed, insertions, deletions


def get_commit_diff_limited(
    repo_path,
    commit_hash,
    excludes,
    max_lines,
    include_sensitive_files=False,
    max_bytes=DEFAULT_MAX_DIFF_BYTES,
):
    return _limited_filtered_diff(
        repo_path,
        ["log", commit_hash, "-1", "-p", "--format=", "--no-color"],
        [
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-status",
            "-r",
            "-M",
            "-z",
            commit_hash,
        ],
        excludes,
        max_lines,
        include_sensitive_files,
        max_bytes,
    )


def get_staged_diff_limited(
    repo_path,
    excludes,
    max_lines,
    include_sensitive_files=False,
    max_bytes=DEFAULT_MAX_DIFF_BYTES,
):
    return _limited_filtered_diff(
        repo_path,
        ["diff", "--cached", "--no-color"],
        ["diff", "--cached", "--name-status", "-z", "-M"],
        excludes,
        max_lines,
        include_sensitive_files,
        max_bytes,
    )


def get_unstaged_diff_limited(
    repo_path,
    excludes,
    max_lines,
    include_sensitive_files=False,
    max_bytes=DEFAULT_MAX_DIFF_BYTES,
):
    return _limited_filtered_diff(
        repo_path,
        ["diff", "--no-color"],
        ["diff", "--name-status", "-z", "-M"],
        excludes,
        max_lines,
        include_sensitive_files,
        max_bytes,
    )


# Backward-compatible unbounded helpers for callers outside the collector.
def get_commit_diff(repo_path, commit_hash, excludes):
    return get_commit_diff_limited(
        repo_path,
        commit_hash,
        excludes,
        0,
        max_bytes=0,
    )[0]


def get_staged_diff(repo_path, excludes):
    return get_staged_diff_limited(repo_path, excludes, 0, max_bytes=0)[0]


def get_unstaged_diff(repo_path, excludes):
    return get_unstaged_diff_limited(repo_path, excludes, 0, max_bytes=0)[0]


def _split_nul_paths(output):
    return [path for path in output.split("\0") if path]


def get_staged_files(repo_path, excludes, include_sensitive_files=False):
    output = _run_git(repo_path, ["diff", "--cached", "--name-only", "-z"])
    return _filter_excludes(
        _split_nul_paths(output),
        excludes,
        include_sensitive_files,
    )


def get_unstaged_files(repo_path, excludes, include_sensitive_files=False):
    output = _run_git(repo_path, ["diff", "--name-only", "-z"])
    return _filter_excludes(
        _split_nul_paths(output),
        excludes,
        include_sensitive_files,
    )


def get_untracked_files(repo_path, excludes, include_sensitive_files=False):
    output = _run_git(
        repo_path,
        ["ls-files", "--others", "--exclude-standard", "-z"],
    )
    return _filter_excludes(
        _split_nul_paths(output),
        excludes,
        include_sensitive_files,
    )
