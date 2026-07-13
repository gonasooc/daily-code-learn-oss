import os
import threading
from datetime import datetime

from lib.git_commands import (
    DEFAULT_MAX_DIFF_BYTES,
    GitCommandError,
    fetch,
    get_current_branch,
    get_commits_by_author,
    get_commit_diff_limited,
    get_staged_diff_limited,
    get_staged_files,
    get_unstaged_diff_limited,
    get_unstaged_files,
    get_untracked_files,
)
from lib.parallel import get_repo_relative_path, run_parallel_over_repos

DEFAULT_MAX_DIFF_LINES = 1200


class ReportCollection(list):
    """List-compatible report results carrying collection diagnostics."""

    def __init__(self, values=(), warnings=None, errors=None):
        super().__init__(values)
        self.warnings = warnings or []
        self.errors = errors or []


def _get_report_options(config):
    report_config = config.get("report", {})
    max_diff_lines = report_config.get("maxDiffLines", DEFAULT_MAX_DIFF_LINES)
    try:
        max_diff_lines = int(max_diff_lines)
    except (TypeError, ValueError):
        max_diff_lines = DEFAULT_MAX_DIFF_LINES
    max_diff_bytes = report_config.get(
        "maxDiffBytes",
        DEFAULT_MAX_DIFF_BYTES,
    )
    try:
        max_diff_bytes = int(max_diff_bytes)
    except (TypeError, ValueError):
        max_diff_bytes = DEFAULT_MAX_DIFF_BYTES

    return {
        "include_uncommitted_diff": report_config.get("includeUncommittedDiff", True),
        "include_sensitive_files": report_config.get("includeSensitiveFiles", False),
        "max_diff_lines": max_diff_lines,
        "max_diff_bytes": max_diff_bytes,
    }


def _truncate_diff(diff, max_lines):
    """diff가 max_lines를 넘으면 앞부분만 남기고 생략 정보를 반환한다."""
    if not diff or max_lines <= 0:
        return diff, False, 0

    lines = diff.split("\n")
    if len(lines) <= max_lines:
        return diff, False, 0

    omitted = len(lines) - max_lines
    truncated = lines[:max_lines]
    truncated.append(f"... 일부 diff 생략: {omitted}줄 ...")
    return "\n".join(truncated), True, omitted


def collect_reports(config, target_date, include_current_changes=None):
    """모든 root를 순회하며 리포트 데이터를 병렬로 수집한다."""
    excludes = config.get("exclude", [])
    report_options = _get_report_options(config)
    include_uncommitted_diff = report_options["include_uncommitted_diff"]
    include_sensitive_files = report_options["include_sensitive_files"]
    max_diff_lines = report_options["max_diff_lines"]
    max_diff_bytes = report_options["max_diff_bytes"]
    if include_current_changes is None:
        include_current_changes = target_date == datetime.now().strftime("%Y-%m-%d")

    fetch_warnings = []
    warning_lock = threading.Lock()

    def _process_repo(repo_path, root, progress):
        """단일 저장소를 처리하여 리포트 딕셔너리를 반환한다. 데이터 없으면 None."""
        project_name = os.path.basename(repo_path)
        root_name = root["name"]
        relative_path = get_repo_relative_path(repo_path, root)
        author_names = root.get("authorNames", [])
        author_emails = root.get("authorEmails", [])

        progress.update(relative_path, "fetching")
        try:
            fetch(repo_path)
        except GitCommandError as error:
            with warning_lock:
                fetch_warnings.append({
                    "repo_path": repo_path,
                    "repo_relative_path": relative_path,
                    "root_name": root_name,
                    "message": str(error),
                })

        progress.update(relative_path, "collecting")
        branch = get_current_branch(repo_path)
        commits = get_commits_by_author(repo_path, author_emails, target_date)

        for commit in commits:
            diff, truncated, omitted = get_commit_diff_limited(
                repo_path,
                commit["hash"],
                excludes,
                max_diff_lines,
                include_sensitive_files,
                max_diff_bytes,
            )
            commit["diff"] = diff
            commit["diff_truncated"] = truncated
            commit["diff_omitted_lines"] = omitted

        staged = []
        unstaged = []
        untracked = []
        staged_diff = ""
        unstaged_diff = ""
        staged_diff_truncated = False
        unstaged_diff_truncated = False
        staged_diff_omitted_lines = 0
        unstaged_diff_omitted_lines = 0

        if include_current_changes:
            staged = get_staged_files(repo_path, excludes, include_sensitive_files)
            unstaged = get_unstaged_files(repo_path, excludes, include_sensitive_files)
            untracked = get_untracked_files(repo_path, excludes, include_sensitive_files)

        if include_current_changes and include_uncommitted_diff:
            staged_diff, staged_diff_truncated, staged_diff_omitted_lines = get_staged_diff_limited(
                repo_path,
                excludes,
                max_diff_lines,
                include_sensitive_files,
                max_diff_bytes,
            )
            unstaged_diff, unstaged_diff_truncated, unstaged_diff_omitted_lines = get_unstaged_diff_limited(
                repo_path,
                excludes,
                max_diff_lines,
                include_sensitive_files,
                max_diff_bytes,
            )

        progress.complete_one()

        if not commits and not staged and not unstaged and not untracked:
            return None

        return {
            "project_name": project_name,
            "repo_relative_path": relative_path,
            "repo_path": repo_path,
            "root_name": root_name,
            "branch": branch,
            "author_names": list(author_names),
            "commits": commits,
            "staged_files": staged,
            "unstaged_files": unstaged,
            "untracked_files": untracked,
            "includes_current_changes": include_current_changes,
            "include_uncommitted_diff": include_uncommitted_diff,
            "staged_diff": staged_diff,
            "unstaged_diff": unstaged_diff,
            "staged_diff_truncated": staged_diff_truncated,
            "unstaged_diff_truncated": unstaged_diff_truncated,
            "staged_diff_omitted_lines": staged_diff_omitted_lines,
            "unstaged_diff_omitted_lines": unstaged_diff_omitted_lines,
        }

    parallel_results = run_parallel_over_repos(config, _process_repo)
    reports = ReportCollection(
        parallel_results,
        warnings=sorted(
            fetch_warnings,
            key=lambda item: (item["root_name"], item["repo_relative_path"]),
        ),
        errors=getattr(parallel_results, "errors", []),
    )

    # 기존 출력 순서 유지: root_name, project_name 기준 정렬
    reports.sort(key=lambda r: (r["root_name"], r["repo_relative_path"]))
    reports.errors.sort(
        key=lambda item: (
            item.get("root_name", ""),
            item.get("repo_relative_path", item.get("repo_path", "")),
        )
    )

    return reports
