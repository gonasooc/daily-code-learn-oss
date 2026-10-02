"""Collect a small, reproducible standup input directly from the selected root."""

import argparse
import json
import os
import re
import sys
import threading
from contextlib import redirect_stdout
from datetime import date as calendar_date, datetime, time, timedelta

from lib.colors import safe_terminal_text
from lib.config import (
    CONFIG_PATH,
    MAX_MISSED_DAYS,
    ConfigError,
    _read_config_file,
    validate_config,
    validate_scrum_config,
)
from lib.git_commands import (
    GitCommandError,
    _run_git,
    fetch,
    get_staged_files,
    get_unstaged_files,
    get_untracked_files,
)
from lib.parallel import get_repo_relative_path, run_parallel_over_repos


EXCLUDED_SUBJECT_PREFIXES = (
    "Merge branch", "Merge pull request", "semantic versioning update", "Version update",
)
_COMMENT = re.compile(r"(?<!\S)#comment(?=\s|$)")
_TIME = re.compile(r"(?<!\S)#time(?=\s|$)")
_TICKET = re.compile(r"^([A-Z][A-Z0-9_]*-\d+)(?=\s|$)")
_TIME_VALUE = re.compile(r"\s+(\S+(?:[ \t]+\d+(?:\.\d+)?[A-Za-z]+)*)")
_DURATION = re.compile(r"(?:(\d+)h(?:\s*(\d+)m)?|(\d+)m)")


def parse_subject(subject):
    """Preserve source text and parse only metadata before the comment marker."""
    comment_marker = _COMMENT.search(subject)
    metadata = subject[:comment_marker.start()] if comment_marker else subject
    ticket_match = _TICKET.match(metadata)
    ticket = ticket_match.group(1) if ticket_match else None
    time_markers = list(_TIME.finditer(metadata))
    time_text = None
    minutes = None
    time_end = None
    if time_markers:
        marker = time_markers[0]
        value = _TIME_VALUE.match(metadata, marker.end())
        if value and not value.group(1).startswith("#"):
            time_text = value.group(1)
            time_end = value.end()
            duration = _DURATION.fullmatch(time_text)
            if duration and len(time_markers) == 1:
                hours, hour_minutes, only_minutes = duration.groups()
                minutes = int(hours or 0) * 60 + int(hour_minutes or only_minutes or 0)
        else:
            time_end = marker.end()

    if comment_marker:
        comment = subject[comment_marker.end():].strip()
    else:
        comment = metadata
        if time_markers:
            comment = comment[:time_markers[0].start()] + comment[time_end:]
        if ticket_match:
            comment = comment[ticket_match.end():]
        comment = comment.strip()
    return {
        "subject": subject, "ticket": ticket, "time_text": time_text,
        "minutes": minutes, "comment": comment,
    }


def _totals(commits):
    return {
        "commit_count": len(commits),
        "known_minutes": sum(item["minutes"] for item in commits if item["minutes"] is not None),
        "untimed_count": sum(item["minutes"] is None for item in commits),
    }


def _range_commits(repo_path, emails, range_start, target_date, cutoff):
    output = _run_git(repo_path, [
        "log", "--exclude=refs/stash", "--all", f"--since-as-filter={range_start} 00:00:00",
        f"--until=@{cutoff}",
        "--pretty=format:%H%x00%cd%x00%ct%x00%ae%x00%s",
        "--date=format-local:%Y-%m-%d %H:%M:%S %z", "--no-decorate", "--no-merges",
    ])
    allowed = {email.strip().casefold() for email in emails}
    commits = []
    seen = set()
    for line in output.split("\n"):
        if not line:
            continue
        fields = line.split("\0", 4)
        if len(fields) != 5:
            raise GitCommandError(repo_path, "log", "스크럼 커밋 메타데이터 형식 오류")
        commit_hash, commit_date, epoch_text, email, subject = fields
        try:
            epoch = int(epoch_text)
        except ValueError as error:
            raise GitCommandError(repo_path, "log", "스크럼 커밋 시간 형식 오류") from error
        if (commit_hash in seen or email.strip().casefold() not in allowed
                or not range_start <= commit_date[:10] <= target_date
                or epoch > cutoff or subject.startswith(EXCLUDED_SUBJECT_PREFIXES)):
            continue
        seen.add(commit_hash)
        commits.append((epoch, {"hash": commit_hash, "date": commit_date, **parse_subject(subject)}))
    commits.sort(key=lambda item: (item[0], item[1]["hash"]), reverse=True)
    return [commit for _epoch, commit in commits]


def _selected_config(config):
    errors = validate_scrum_config(config, required=True)
    if errors:
        raise ConfigError("; ".join(errors))
    selected = {
        "roots": [root for root in config["roots"] if isinstance(root, dict)
                  and root.get("name") == config["scrum"]["root"]],
        "outputDir": ".",
        "exclude": config.get("exclude", []),
        "report": config.get("report", {}),
        "telegram": {"enabled": False},
    }
    errors = validate_config(selected)
    if errors:
        raise ConfigError("; ".join(errors))
    return selected


def collect_scrum(config, target_date=None, days=30, now=None):
    """Return live source evidence; never read or write daily/standup reports."""
    now = now or datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.astimezone()
    if target_date is None:
        target_date = now.date().isoformat()
    target = calendar_date.fromisoformat(target_date)
    if target.isoformat() != target_date or target > now.date():
        raise ValueError("대상 날짜는 오늘 이하의 YYYY-MM-DD여야 합니다.")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_MISSED_DAYS:
        raise ValueError(f"days는 1 이상 {MAX_MISSED_DAYS} 이하의 정수여야 합니다.")
    selected = _selected_config(config)
    range_start = (target - timedelta(days=days)).isoformat()
    cutoff = min(int(now.timestamp()), int(datetime.combine(target, time.max).astimezone().timestamp()))
    include_wip = target == now.date()
    warnings = []
    warning_lock = threading.Lock()
    excludes = selected["exclude"]
    include_sensitive = selected["report"].get("includeSensitiveFiles", False)

    def process(repo_path, root, progress):
        relative = get_repo_relative_path(repo_path, root)
        progress.update(relative, "fetching")
        try:
            fetch(repo_path)
        except GitCommandError as error:
            with warning_lock:
                warnings.append({"root_name": root["name"], "repo_relative_path": relative, "message": str(error)})
        progress.update(relative, "collecting")
        commits = _range_commits(repo_path, root["authorEmails"], range_start, target_date, cutoff)
        files = set()
        if include_wip:
            for get_files in (get_staged_files, get_unstaged_files, get_untracked_files):
                files.update(get_files(repo_path, excludes, include_sensitive))
        progress.complete_one()
        return {
            "repository": f"{root['name']}/{relative}", "commits": commits,
            "wip": {
                "count": len(files), "files": sorted(files),
                "directories": sorted({path.split("/", 1)[0] if "/" in path else "." for path in files}),
            },
        }

    with redirect_stdout(sys.stderr):
        collected = run_parallel_over_repos(selected, process)
    previous_date = max((commit["date"][:10] for project in collected for commit in project["commits"]
                         if commit["date"][:10] < target_date), default=None)
    projects = []
    for project in collected:
        project["commits"] = [commit for commit in project["commits"] if commit["date"][:10] in {previous_date, target_date}]
        if project["commits"] or project["wip"]["count"]:
            project["totals"] = _totals(project["commits"])
            projects.append(project)
    projects.sort(key=lambda project: project["repository"])
    errors = sorted(getattr(collected, "errors", []), key=lambda issue: (issue.get("root_name", ""), issue.get("repo_relative_path", "")))
    if not collected and not errors:
        errors.append({"root_name": config["scrum"]["root"], "repo_relative_path": ".",
                       "message": "선택한 scrum.root에서 Git 저장소를 찾지 못했습니다. path와 maxDepth를 확인하세요."})
    warnings.sort(key=lambda issue: (issue["root_name"], issue["repo_relative_path"]))
    totals = _totals([commit for project in projects for commit in project["commits"]])
    totals.update(project_count=len(projects), wip_file_count=sum(project["wip"]["count"] for project in projects))
    return {
        "date": target_date, "previous_work_date": previous_date, "range_start": range_start,
        "captured_at": now.isoformat(timespec="seconds"),
        "output_path": os.path.abspath(os.path.join(config["scrum"]["outputDir"], f"{target_date}.md")),
        "complete": not (warnings or errors), "projects": projects,
        "totals": totals, "warnings": warnings, "errors": errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="선택한 업무 root의 스크럼 입력을 JSON으로 수집")
    parser.add_argument("--date", help="대상 날짜 YYYY-MM-DD (기본: 오늘)")
    parser.add_argument("--days", type=int, default=30, help="이전 작업일 탐색 범위 (기본: 30일)")
    args = parser.parse_args(argv)
    try:
        result = collect_scrum(_read_config_file(CONFIG_PATH), args.date, args.days)
    except (ConfigError, ValueError, OSError, OverflowError) as error:
        result = {"complete": False, "projects": [], "warnings": [], "errors": [{"message": str(error)}]}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    for issue in result["warnings"] + result["errors"]:
        print(safe_terminal_text(issue["message"]), file=sys.stderr)
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
