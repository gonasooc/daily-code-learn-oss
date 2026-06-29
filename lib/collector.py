import os

from lib.git_commands import (
    fetch,
    get_current_branch,
    get_commits_by_author,
    get_commit_diff,
    get_staged_diff,
    get_staged_files,
    get_unstaged_diff,
    get_unstaged_files,
    get_untracked_files,
)
from lib.parallel import run_parallel_over_repos

DEFAULT_MAX_DIFF_LINES = 1200


def _get_report_options(config):
    report_config = config.get("report", {})
    max_diff_lines = report_config.get("maxDiffLines", DEFAULT_MAX_DIFF_LINES)
    try:
        max_diff_lines = int(max_diff_lines)
    except (TypeError, ValueError):
        max_diff_lines = DEFAULT_MAX_DIFF_LINES

    return {
        "include_uncommitted_diff": report_config.get("includeUncommittedDiff", True),
        "max_diff_lines": max_diff_lines,
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


def collect_reports(config, target_date):
    """모든 root를 순회하며 리포트 데이터를 병렬로 수집한다."""
    excludes = config.get("exclude", [])
    report_options = _get_report_options(config)
    include_uncommitted_diff = report_options["include_uncommitted_diff"]
    max_diff_lines = report_options["max_diff_lines"]

    def _process_repo(repo_path, root, progress):
        """단일 저장소를 처리하여 리포트 딕셔너리를 반환한다. 데이터 없으면 None."""
        project_name = os.path.basename(repo_path)
        root_name = root["name"]
        author_names = root.get("authorNames", [])
        author_emails = root.get("authorEmails", [])

        progress.update(project_name, "fetching")
        fetch(repo_path)

        progress.update(project_name, "collecting")
        branch = get_current_branch(repo_path)
        commits = get_commits_by_author(repo_path, author_emails, target_date)

        for commit in commits:
            diff, truncated, omitted = _truncate_diff(
                get_commit_diff(repo_path, commit["hash"], excludes),
                max_diff_lines,
            )
            commit["diff"] = diff
            commit["diff_truncated"] = truncated
            commit["diff_omitted_lines"] = omitted

        staged = get_staged_files(repo_path, excludes)
        unstaged = get_unstaged_files(repo_path, excludes)
        untracked = get_untracked_files(repo_path, excludes)
        staged_diff = ""
        unstaged_diff = ""
        staged_diff_truncated = False
        unstaged_diff_truncated = False
        staged_diff_omitted_lines = 0
        unstaged_diff_omitted_lines = 0

        if include_uncommitted_diff:
            staged_diff, staged_diff_truncated, staged_diff_omitted_lines = _truncate_diff(
                get_staged_diff(repo_path, excludes),
                max_diff_lines,
            )
            unstaged_diff, unstaged_diff_truncated, unstaged_diff_omitted_lines = _truncate_diff(
                get_unstaged_diff(repo_path, excludes),
                max_diff_lines,
            )

        progress.complete_one()

        if not commits and not staged and not unstaged and not untracked:
            return None

        author_name = author_names[0] if author_names else ""
        author_email = author_emails[0] if author_emails else ""

        return {
            "project_name": project_name,
            "repo_path": repo_path,
            "root_name": root_name,
            "branch": branch,
            "author_name": author_name,
            "author_email": author_email,
            "commits": commits,
            "staged_files": staged,
            "unstaged_files": unstaged,
            "untracked_files": untracked,
            "include_uncommitted_diff": include_uncommitted_diff,
            "staged_diff": staged_diff,
            "unstaged_diff": unstaged_diff,
            "staged_diff_truncated": staged_diff_truncated,
            "unstaged_diff_truncated": unstaged_diff_truncated,
            "staged_diff_omitted_lines": staged_diff_omitted_lines,
            "unstaged_diff_omitted_lines": unstaged_diff_omitted_lines,
        }

    reports = run_parallel_over_repos(config, _process_repo)

    # 기존 출력 순서 유지: root_name, project_name 기준 정렬
    reports.sort(key=lambda r: (r["root_name"], r["project_name"]))

    return reports
