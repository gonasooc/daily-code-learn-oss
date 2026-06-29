import os


def render_markdown(report, date):
    """리포트 딕셔너리를 마크다운 문자열로 변환한다."""
    lines = []
    project_name = report["project_name"]

    lines.append(f"# {date} - {project_name}")
    lines.append("")

    # 기본 정보
    lines.append("## 기본 정보")
    lines.append(f"- 경로: {report['repo_path']}")
    lines.append(f"- 브랜치: {report['branch']}")
    lines.append(f"- 작성자: {report['author_name']} <{report['author_email']}>")
    lines.append("")

    _append_work_summary(lines, report)

    # 커밋
    if report["commits"]:
        lines.append("## 오늘 커밋")
        for commit in report["commits"]:
            lines.append(f"### {commit['subject']}")
            lines.append(f"- Hash: {commit['hash'][:7]}")
            time_part = _extract_time(commit["date"])
            lines.append(f"- 시간: {time_part}")
            lines.append(f"- 변경: {commit['files_changed']} files (+{commit['insertions']} -{commit['deletions']})")
            if commit.get("diff_truncated"):
                omitted = commit.get("diff_omitted_lines", 0)
                lines.append(f"- Diff: 일부 diff 생략 ({omitted}줄)")

            if commit.get("diff"):
                _append_diff_details(lines, "diff 보기", commit["diff"])

            lines.append("")

    # 현재 작업 중 변경
    has_staged = bool(report["staged_files"])
    has_unstaged = bool(report["unstaged_files"])
    has_untracked = bool(report.get("untracked_files", []))

    if has_staged or has_unstaged or has_untracked:
        lines.append("## 현재 작업 중 변경")

        if has_staged:
            _append_uncommitted_change(
                lines,
                "Staged",
                report["staged_files"],
                report.get("staged_diff", ""),
                report.get("include_uncommitted_diff", True),
                report.get("staged_diff_truncated", False),
                report.get("staged_diff_omitted_lines", 0),
            )

        if has_unstaged:
            _append_uncommitted_change(
                lines,
                "Unstaged",
                report["unstaged_files"],
                report.get("unstaged_diff", ""),
                report.get("include_uncommitted_diff", True),
                report.get("unstaged_diff_truncated", False),
                report.get("unstaged_diff_omitted_lines", 0),
            )

        if has_untracked:
            _append_file_list(lines, "Untracked", report.get("untracked_files", []))

    return "\n".join(lines)


def _append_work_summary(lines, report):
    """리포트 상단에 프로젝트 단위 작업량 요약을 추가한다."""
    commits = report["commits"]
    staged_files = report["staged_files"]
    unstaged_files = report["unstaged_files"]
    untracked_files = report.get("untracked_files", [])
    commit_files = sum(commit.get("files_changed", 0) for commit in commits)
    insertions = sum(commit.get("insertions", 0) for commit in commits)
    deletions = sum(commit.get("deletions", 0) for commit in commits)

    lines.append("## 오늘 작업 요약")
    lines.append(f"- 커밋: {len(commits)}건")
    lines.append(f"- 커밋 변경량: {commit_files} files (+{insertions} -{deletions})")
    lines.append(f"- Staged: {len(staged_files)} files")
    lines.append(f"- Unstaged: {len(unstaged_files)} files")
    lines.append(f"- Untracked: {len(untracked_files)} files")
    lines.append("")


def _append_diff_details(lines, summary, diff):
    """diff를 details 코드블록으로 추가한다."""
    lines.append("")
    lines.append("<details>")
    lines.append(f"<summary>{summary}</summary>")
    lines.append("")
    lines.append("```diff")
    lines.append(diff)
    lines.append("```")
    lines.append("")
    lines.append("</details>")


def _append_uncommitted_change(lines, title, files, diff, include_diff, truncated, omitted_lines):
    """staged/unstaged 변경 목록과 diff를 추가한다."""
    lines.append(f"### {title}")
    for f in files:
        lines.append(f"- {f}")

    if not include_diff:
        lines.append("- diff: 설정에서 비활성화됨")
        lines.append("")
        return

    if truncated:
        lines.append(f"- Diff: 일부 diff 생략 ({omitted_lines}줄)")

    if diff:
        _append_diff_details(lines, f"{title.lower()} diff 보기", diff)

    lines.append("")


def _append_file_list(lines, title, files):
    """diff 없이 파일 목록만 추가한다."""
    lines.append(f"### {title}")
    for f in files:
        lines.append(f"- {f}")
    lines.append("")


def _extract_time(date_str):
    """ISO 날짜 문자열에서 HH:mm을 추출한다."""
    try:
        # "2026-03-12 14:30:00 +0900" 형태
        parts = date_str.strip().split(" ")
        if len(parts) >= 2:
            time_parts = parts[1].split(":")
            return f"{time_parts[0]}:{time_parts[1]}"
    except Exception:
        pass
    return date_str


def write_report(report, date, output_dir):
    """마크다운 리포트를 파일로 저장한다."""
    dir_path = os.path.join(output_dir, date)
    os.makedirs(dir_path, exist_ok=True)

    file_path = os.path.join(dir_path, f"{report['project_name']}.md")
    content = render_markdown(report, date)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    return file_path
