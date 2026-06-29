import fnmatch
import logging
import re
import subprocess

logger = logging.getLogger(__name__)


def _run_git(repo_path, args):
    """git 명령을 실행하고 stdout을 반환한다. 실패 시 빈 문자열."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path] + args,
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.debug("git %s failed in %s: %s", args[0], repo_path, result.stderr.strip())
        return result.stdout.strip()
    except Exception as e:
        logger.debug("git %s error in %s: %s", args[0], repo_path, e)
        return ""


def _is_excluded(path, excludes):
    """파일 경로가 exclude 항목에 해당하면 True를 반환한다."""
    normalized_path = path.replace("\\", "/")
    for exclude in excludes:
        pattern = str(exclude).strip().replace("\\", "/")
        if not pattern:
            continue
        if pattern in normalized_path:
            return True
        if fnmatch.fnmatch(normalized_path, pattern):
            return True
    return False


def _filter_excludes(files, excludes):
    """파일 경로에 exclude 항목이 포함되거나 glob 패턴과 맞으면 제외한다."""
    filtered = []
    for f in files:
        if not _is_excluded(f, excludes):
            filtered.append(f)
    return filtered


def _diff_paths_from_header(line):
    """diff --git 헤더에서 a/b 경로를 추출한다."""
    match = re.match(r"^diff --git a/(.*?) b/(.*)$", line)
    if match:
        return [match.group(1), match.group(2)]

    parts = line.split()
    paths = []
    for value in parts[2:4]:
        if value.startswith("a/") or value.startswith("b/"):
            paths.append(value[2:])
    return paths


def _filter_diff_excludes(output, excludes):
    """diff 출력에서 exclude 대상 파일 블록을 제거한다."""
    if not output:
        return ""

    filtered = []
    skip_file = False

    for line in output.split("\n"):
        if line.startswith("diff --git"):
            paths = _diff_paths_from_header(line)
            skip_file = any(_is_excluded(path, excludes) for path in paths)

        if not skip_file:
            filtered.append(line)

    return "\n".join(filtered).strip()


def fetch(repo_path):
    """원격 브랜치 정보를 가져온다 (워킹 디렉토리 변경 없음)."""
    _run_git(repo_path, ["fetch", "--quiet"])


def get_current_branch(repo_path):
    return _run_git(repo_path, ["branch", "--show-current"])


def get_commits_by_author(repo_path, author_emails, date):
    """해당 날짜에 author_emails로 작성된 커밋 목록을 반환한다."""
    seen_hashes = set()
    commits = []

    for email in author_emails:
        output = _run_git(repo_path, [
            "log", "--all",
            f"--since={date} 00:00:00",
            f"--until={date} 23:59:59",
            f"--author={email}",
            "--pretty=format:%H|%ad|%s",
            "--date=iso",
            "--shortstat",
        ])
        if not output:
            continue

        lines = output.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            parts = line.split("|", 2)
            if len(parts) < 3:
                i += 1
                continue

            hash_val, date_str, subject = parts
            # 다음 줄이 shortstat일 수 있음
            stat_line = ""
            if i + 1 < len(lines) and lines[i + 1].strip() and "|" not in lines[i + 1]:
                stat_line = lines[i + 1].strip()
                i += 2
            else:
                i += 1

            if hash_val in seen_hashes:
                continue
            seen_hashes.add(hash_val)

            files_changed, insertions, deletions = _parse_shortstat(stat_line)

            commits.append({
                "hash": hash_val,
                "date": date_str,
                "subject": subject,
                "files_changed": files_changed,
                "insertions": insertions,
                "deletions": deletions,
            })

    return commits


def get_commit_dates_by_author(repo_path, author_emails, start_date, end_date):
    """기간 내 author_emails로 작성된 커밋을 날짜별로 집계한다."""
    seen_hashes = set()
    commit_dates = {}

    for email in author_emails:
        output = _run_git(repo_path, [
            "log", "--all",
            f"--since={start_date} 00:00:00",
            f"--until={end_date} 23:59:59",
            f"--author={email}",
            "--pretty=format:%H|%ad",
            "--date=short",
        ])
        if not output:
            continue

        for line in output.split("\n"):
            parts = line.split("|", 1)
            if len(parts) < 2:
                continue

            hash_val, date_str = parts
            if hash_val in seen_hashes:
                continue

            seen_hashes.add(hash_val)
            commit_dates[date_str] = commit_dates.get(date_str, 0) + 1

    return commit_dates


def _parse_shortstat(stat_str):
    """shortstat 출력을 파싱하여 (files_changed, insertions, deletions) 반환."""
    files_changed = 0
    insertions = 0
    deletions = 0

    if not stat_str:
        return files_changed, insertions, deletions

    m = re.search(r"(\d+) file", stat_str)
    if m:
        files_changed = int(m.group(1))
    m = re.search(r"(\d+) insertion", stat_str)
    if m:
        insertions = int(m.group(1))
    m = re.search(r"(\d+) deletion", stat_str)
    if m:
        deletions = int(m.group(1))

    return files_changed, insertions, deletions


def get_commit_diff(repo_path, commit_hash, excludes):
    """커밋의 실제 코드 diff를 반환한다."""
    output = _run_git(repo_path, [
        "log", commit_hash, "-1", "-p",
        "--format=",
        "--no-color",
    ])
    return _filter_diff_excludes(output, excludes)


def get_staged_diff(repo_path, excludes):
    """staged 변경의 실제 코드 diff를 반환한다."""
    output = _run_git(repo_path, ["diff", "--cached", "--no-color"])
    return _filter_diff_excludes(output, excludes)


def get_unstaged_diff(repo_path, excludes):
    """unstaged 변경의 실제 코드 diff를 반환한다."""
    output = _run_git(repo_path, ["diff", "--no-color"])
    return _filter_diff_excludes(output, excludes)


def get_staged_files(repo_path, excludes):
    output = _run_git(repo_path, ["diff", "--cached", "--name-only"])
    if not output:
        return []
    files = [f for f in output.split("\n") if f]
    return _filter_excludes(files, excludes)


def get_unstaged_files(repo_path, excludes):
    output = _run_git(repo_path, ["diff", "--name-only"])
    if not output:
        return []
    files = [f for f in output.split("\n") if f]
    return _filter_excludes(files, excludes)


def get_untracked_files(repo_path, excludes):
    output = _run_git(repo_path, ["ls-files", "--others", "--exclude-standard"])
    if not output:
        return []
    files = [f for f in output.split("\n") if f]
    return _filter_excludes(files, excludes)
