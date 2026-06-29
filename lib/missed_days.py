import os
from datetime import datetime, timedelta

from lib.git_commands import fetch, get_commit_dates_by_author
from lib.colors import green, yellow, red, cyan, dim, bold
from lib.parallel import run_parallel_over_repos


def _has_report(output_dir, date_str):
    """해당 날짜의 리포트 디렉토리에 프로젝트 리포트가 있는지 확인한다."""
    report_dir = os.path.join(output_dir, date_str)
    if not os.path.isdir(report_dir):
        return False
    for name in os.listdir(report_dir):
        if name.endswith(".md") and not _is_analysis_file(name):
            return True
    return False


def _is_analysis_file(name):
    return name == "analysis.md" or name.endswith("-analysis.md")


def _format_project_name(root_name, repo_path):
    project_name = os.path.basename(repo_path)
    return f"{root_name}/{project_name}"


def collect_missed_days(config, days, today=None):
    """최근 N일 동안 작업했지만 리포트가 없는 날짜를 수집한다."""
    today = today or datetime.now().date()
    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=days - 1)
    output_dir = config["outputDir"]

    activity_by_date = {}

    def _process_repo(repo_path, root, progress):
        root_name = root["name"]
        author_emails = root.get("authorEmails", [])
        project_name = _format_project_name(root_name, repo_path)
        progress.update(os.path.basename(repo_path), "fetching")
        fetch(repo_path)
        progress.update(os.path.basename(repo_path), "collecting")
        commit_dates = get_commit_dates_by_author(
            repo_path, author_emails,
            start_date.isoformat(), end_date.isoformat(),
        )
        progress.complete_one()
        if not commit_dates:
            return None
        return project_name, commit_dates

    results = run_parallel_over_repos(config, _process_repo)

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
            "has_report": _has_report(output_dir, date_str),
        })

    missed_days = [entry for entry in activity_days if not entry["has_report"]]

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "activity_days": activity_days,
        "missed_days": missed_days,
    }


def _is_valid_date_input(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
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
        projects = ", ".join(entry["project_names"])
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
