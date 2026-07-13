#!/usr/bin/env python3
"""Daily Code Learn - 오늘 작업한 코드를 프로젝트별 마크다운으로 정리"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import load_config, parse_args, init_config, run_doctor
from lib.collector import collect_reports
from lib.missed_days import collect_missed_days, pick_missed_day
from lib.renderer import build_report_filename, write_report
from lib.notifier import notify
from lib.colors import green, yellow, red, cyan, dim, bold, safe_terminal_text
from lib.parallel import get_repo_relative_path


def _issue_repo_label(issue, config=None):
    relative_path = issue.get("repo_relative_path")
    if relative_path:
        return safe_terminal_text(relative_path)

    repo_path = issue.get("repo_path", "")
    if config and repo_path:
        root_name = issue.get("root_name")
        for root in config.get("roots", []):
            if root.get("name") == root_name:
                return safe_terminal_text(get_repo_relative_path(repo_path, root))

    return safe_terminal_text(
        os.path.basename(os.path.normpath(repo_path)) or "?"
    )


def _print_collection_issues(warnings, errors, config=None):
    for issue in warnings:
        root_name = safe_terminal_text(issue.get("root_name", "?"))
        message = safe_terminal_text(issue.get("message", "수집 경고"))
        label = f"[{root_name}] {_issue_repo_label(issue, config)}"
        print(yellow(f"  [경고] {label}: {message}"))
    for issue in errors:
        root_name = safe_terminal_text(issue.get("root_name", "?"))
        message = safe_terminal_text(issue.get("message", "수집 실패"))
        label = f"[{root_name}] {_issue_repo_label(issue, config)}"
        print(red(f"  [오류] {label}: {message}"))


def generate_reports_for_date(
    config,
    date,
    notify_after_generate=False,
    include_current_changes=None,
):
    output_dir = config["outputDir"]
    reports = collect_reports(
        config,
        date,
        include_current_changes=include_current_changes,
    )
    warnings = getattr(reports, "warnings", [])
    errors = getattr(reports, "errors", [])
    has_collection_issues = bool(warnings or errors)

    if not reports:
        if has_collection_issues:
            print(red(f"[{date}] 저장소 수집이 실패했거나 불완전합니다."))
        else:
            print(yellow(f"[{date}] 작업 이력이 있는 저장소가 없습니다."))
        _print_collection_issues(warnings, errors, config)
        return 1 if has_collection_issues else 0

    written_paths = []
    write_errors = []
    claimed_filenames = set()
    for report in reports:
        try:
            report_filename = build_report_filename(report)
            if report_filename in claimed_filenames:
                raise ValueError(
                    f"리포트 파일명 충돌 감지: {report_filename}"
                )
            claimed_filenames.add(report_filename)
            file_path = write_report(report, date, output_dir)
        except (OSError, UnicodeError, ValueError) as error:
            write_errors.append({
                "root_name": report["root_name"],
                "repo_path": report["repo_path"],
                "repo_relative_path": report.get(
                    "repo_relative_path", report["project_name"]
                ),
                "message": f"리포트 쓰기 실패: {error}",
            })
            continue

        written_paths.append(file_path)
        commit_count = len(report["commits"])
        staged_count = len(report["staged_files"])
        unstaged_count = len(report["unstaged_files"])
        untracked_count = len(report.get("untracked_files", []))
        root_name = safe_terminal_text(report["root_name"])
        project_name = safe_terminal_text(
            report.get("repo_relative_path", report["project_name"])
        )
        root_label = cyan("[" + root_name + "]")
        proj_label = bold(project_name)
        display_path = safe_terminal_text(file_path)
        print(f"  {root_label} {proj_label}: "
              f"커밋 {green(str(commit_count) + '건')}, staged {yellow(str(staged_count) + '건')}, "
              f"unstaged {yellow(str(unstaged_count) + '건')}, untracked {yellow(str(untracked_count) + '건')} → {dim(display_path)}")

    count = len(written_paths)
    if write_errors and count:
        summary = yellow(
            f"프로젝트 리포트 {count}개 생성, {len(write_errors)}개 쓰기 실패"
        )
    elif write_errors:
        summary = red(f"프로젝트 리포트 생성 실패 ({len(write_errors)}개)")
    elif has_collection_issues:
        summary = yellow(
            f"프로젝트 리포트 {count}개 생성, 저장소 수집 불완전"
        )
    else:
        summary = green(f"총 {count}개 프로젝트 리포트 생성 완료")
    print(f"\n{summary} ({date})")
    _print_collection_issues(warnings, errors + write_errors, config)

    notify_failed = False
    if notify_after_generate and written_paths:
        try:
            notify_ok = notify(
                config,
                date,
                output_dir,
                file_paths=written_paths,
            )
        except Exception as error:
            print(red(
                "[텔레그램] 알림 처리 실패: "
                + safe_terminal_text(type(error).__name__)
            ))
            notify_failed = True
        else:
            notify_failed = not notify_ok

    if has_collection_issues or write_errors or notify_failed:
        return 1

    return 0


def main():
    args = parse_args()

    if args.init:
        return init_config()

    if args.doctor:
        return run_doctor()

    if args.no_notify:
        print(dim("[안내] --no-notify 는 더 이상 필요 없습니다. 기본 동작은 전송 안 함이며, 전송이 필요하면 --notify 를 사용하세요."))

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")

    config = load_config()

    if args.check_missed:
        result = collect_missed_days(config, args.days)
        scan_warnings = result.get("warnings", [])
        scan_errors = result.get("errors", [])
        _print_collection_issues(scan_warnings, scan_errors, config)
        scan_incomplete = bool(scan_warnings or scan_errors)
        selected_date = pick_missed_day(result, args.days)
        if not selected_date:
            return 1 if scan_incomplete else 0

        print("")
        exit_code = generate_reports_for_date(
            config,
            selected_date,
            notify_after_generate=args.notify,
            include_current_changes=args.include_current_changes,
        )
        if exit_code == 0:
            output_dir = config["outputDir"]
            selected_path = safe_terminal_text(
                os.path.join(output_dir, selected_date)
            )
            print(f"\n{cyan('선택한 날짜 리포트 경로:')} {bold(selected_path)}")
            print(f"{dim('다음 단계:')} Codex/Claude로 {selected_path} 분석 진행")
        return 1 if scan_incomplete else exit_code

    return generate_reports_for_date(
        config,
        args.date,
        notify_after_generate=args.notify,
        include_current_changes=args.include_current_changes,
    )


if __name__ == "__main__":
    sys.exit(main())
