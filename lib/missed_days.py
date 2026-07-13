import os
import re
import stat
import threading
from datetime import datetime, timedelta

from lib.git_commands import GitCommandError, fetch, get_commit_dates_by_author
from lib.colors import green, yellow, red, cyan, dim, bold, safe_terminal_text
from lib.parallel import get_repo_relative_path, run_parallel_over_repos


_REPORT_IDENTITY_MARKER_RE = re.compile(
    r"<!-- daily-code-learn-report:v1:[0-9a-f]{64} -->"
)


def _has_report(output_dir, date_str, on_error=None):
    """해당 날짜의 리포트 디렉토리에 프로젝트 리포트가 있는지 확인한다.

    파일명만으로는 사용자가 작성한 일반 Markdown과 생성된 리포트를
    구분할 수 없으므로 현재 identity marker 또는 기존 리포트 구조를
    첫 줄 날짜 헤더와 함께 확인한다.
    on_error가 주어지면 읽기 오류를 전달하고 나머지 파일 확인을 계속한다.
    """
    report_dir = os.path.join(output_dir, date_str)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    report_directory_fd = None
    try:
        report_directory_fd = os.open(report_dir, directory_flags)
        if not stat.S_ISDIR(os.fstat(report_directory_fd).st_mode):
            raise NotADirectoryError(report_dir)
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError) as error:
        if report_directory_fd is not None:
            os.close(report_directory_fd)
        if on_error is None:
            raise
        on_error(report_dir, error)
        return False

    try:
        try:
            names = os.listdir(report_directory_fd)
        except (OSError, UnicodeError) as error:
            if on_error is None:
                raise
            on_error(report_dir, error)
            return False

        expected_header = f"# {date_str} - "
        for name in sorted(names):
            if not name.endswith(".md"):
                continue
            report_path = os.path.join(report_dir, name)
            flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            file_descriptor = None
            try:
                file_descriptor = os.open(
                    name,
                    flags,
                    dir_fd=report_directory_fd,
                )
                if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
                    raise OSError("일반 Markdown 파일이 아닙니다.")
                with os.fdopen(
                    file_descriptor,
                    "r",
                    encoding="utf-8",
                ) as report_file:
                    file_descriptor = None
                    first_lines = [
                        report_file.readline(64 * 1024).rstrip("\n")
                        for _index in range(3)
                    ]
            except (OSError, UnicodeError) as error:
                if on_error is None:
                    raise
                on_error(report_path, error)
                continue
            finally:
                if file_descriptor is not None:
                    os.close(file_descriptor)
            first_line, second_line, third_line = first_lines
            has_current_marker = bool(
                _REPORT_IDENTITY_MARKER_RE.fullmatch(second_line.strip())
            )
            has_legacy_structure = (
                second_line == ""
                and third_line.strip() == "## 기본 정보"
            )
            if (
                first_line.startswith(expected_header)
                and (has_current_marker or has_legacy_structure)
            ):
                return True
        return False
    finally:
        os.close(report_directory_fd)


def _format_project_name(root_name, root_path, repo_path):
    relative_path = get_repo_relative_path(repo_path, {"path": root_path})
    return f"{root_name}/{relative_path}"


def collect_missed_days(config, days, today=None):
    """최근 N일 동안 작업했지만 리포트가 없는 날짜를 수집한다."""
    today = today or datetime.now().date()
    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=days - 1)
    output_dir = config["outputDir"]

    activity_by_date = {}
    fetch_warnings = []
    warning_lock = threading.Lock()

    def _process_repo(repo_path, root, progress):
        root_name = root["name"]
        author_emails = root.get("authorEmails", [])
        project_name = _format_project_name(root_name, root["path"], repo_path)
        relative_path = get_repo_relative_path(repo_path, root)
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
        commit_dates = get_commit_dates_by_author(
            repo_path, author_emails,
            start_date.isoformat(), end_date.isoformat(),
        )
        progress.complete_one()
        if not commit_dates:
            return None
        return project_name, commit_dates

    results = run_parallel_over_repos(config, _process_repo)
    report_errors = []

    def _record_report_error(path, error):
        try:
            relative_path = os.path.relpath(path, output_dir).replace(os.sep, "/")
        except (OSError, TypeError, ValueError):
            relative_path = os.path.basename(os.path.normpath(path)) or "?"
        report_errors.append({
            "repo_path": path,
            "repo_relative_path": relative_path,
            "root_name": "reports",
            "message": f"리포트 확인 실패: {error}",
        })

    for project_name, commit_dates in results:
        for date_str, commit_count in commit_dates.items():
            entry = activity_by_date.setdefault(date_str, {
                "date": date_str,
                "project_names": set(),
                "commit_count": 0,
            })
            entry["project_names"].add(project_name)
            entry["commit_count"] += commit_count

    activity_days = []
    for date_str in sorted(activity_by_date):
        entry = activity_by_date[date_str]
        project_names = sorted(entry["project_names"])
        activity_days.append({
            "date": date_str,
            "project_names": project_names,
            "project_count": len(project_names),
            "commit_count": entry["commit_count"],
            "has_report": _has_report(
                output_dir,
                date_str,
                on_error=_record_report_error,
            ),
        })

    missed_days = [entry for entry in activity_days if not entry["has_report"]]

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "activity_days": activity_days,
        "missed_days": missed_days,
        "warnings": sorted(
            fetch_warnings,
            key=lambda item: (item["root_name"], item["repo_relative_path"]),
        ),
        "errors": sorted(
            list(getattr(results, "errors", [])) + report_errors,
            key=lambda item: (
                item.get("root_name", ""),
                item.get("repo_relative_path", item.get("repo_path", "")),
            ),
        ),
    }


def _is_valid_date_input(value):
    try:
        parsed_date = datetime.strptime(value, "%Y-%m-%d")
        return parsed_date.strftime("%Y-%m-%d") == value
    except ValueError:
        return False


def pick_missed_day(result, days, input_func=input, max_display=10):
    missed_days = result["missed_days"]
    activity_days = result["activity_days"]

    if not activity_days:
        print(yellow(f"[최근 {days}일] 작업 이력이 있는 날짜가 없습니다."))
        return None

    if not missed_days:
        print(green(f"[최근 {days}일] 누락된 학습일이 없습니다."))
        return None

    missed_days = sorted(missed_days, key=lambda entry: entry["date"], reverse=True)
    shown_days = missed_days[:max_display]
    missed_days_by_date = {entry["date"]: entry for entry in missed_days}

    missed_count = str(len(missed_days))
    date_range = "(" + result["start_date"] + " ~ " + result["end_date"] + ")"
    print(
        yellow("[최근 " + str(days) + "일]")
        + " 작업했지만 리포트를 만들지 않은 날짜 " + bold(missed_count + "일")
        + " " + dim(date_range)
    )
    print("")

    for index, entry in enumerate(shown_days, start=1):
        projects = ", ".join(
            safe_terminal_text(project_name)
            for project_name in entry["project_names"]
        )
        proj_count = str(entry["project_count"])
        commit_count = str(entry["commit_count"])
        print(
            f"{bold(str(index) + '.')} {cyan(entry['date'])}: 프로젝트 {green(proj_count + '개')}, "
            f"커밋 {green(commit_count + '건')}"
        )
        print(f"  {dim('프로젝트:')} {projects}")
    if len(missed_days) > max_display:
        print("")
        print(dim(f"최신 {max_display}개만 번호로 표시했습니다. 더 오래된 날짜는 YYYY-MM-DD로 직접 입력하세요."))

    print("")
    print(dim("번호를 입력하거나 날짜(YYYY-MM-DD)를 직접 입력하세요. 취소하려면 Enter/q"))

    while True:
        try:
            raw = input_func("> ").strip()
        except EOFError:
            print(yellow("입력이 종료되어 취소합니다."))
            return None

        if not raw or raw.lower() in {"q", "quit"}:
            print(dim("취소했습니다."))
            return None

        if raw.isdigit():
            # Python 3.11+ intentionally rejects extremely long decimal
            # strings.  Reject them before int() so interactive input can
            # never turn into a traceback.
            if len(raw) > max(6, len(str(len(shown_days))) + 1):
                print(red(f"1부터 {len(shown_days)} 사이 번호를 입력하세요."))
                continue
            index = int(raw)
            if 1 <= index <= len(shown_days):
                selected_date = shown_days[index - 1]["date"]
                print(f"{green('선택한 날짜:')} {bold(selected_date)}")
                return selected_date
            print(red(f"1부터 {len(shown_days)} 사이 번호를 입력하세요."))
            continue

        if _is_valid_date_input(raw):
            if raw in missed_days_by_date:
                print(f"{green('선택한 날짜:')} {bold(raw)}")
                return raw
            print(red("누락 날짜 목록에 없는 날짜입니다."))
            continue

        print(red("잘못된 입력입니다. 번호 또는 YYYY-MM-DD 형식으로 입력하세요."))
