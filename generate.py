#!/usr/bin/env python3
"""Daily Code Learn - 오늘 작업한 코드를 프로젝트별 마크다운으로 정리"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import load_config, parse_args, init_config, run_doctor
from lib.collector import collect_reports
from lib.missed_days import collect_missed_days, pick_missed_day
from lib.renderer import write_report
from lib.notifier import notify
from lib.colors import green, yellow, cyan, dim, bold


def generate_reports_for_date(config, date, notify_after_generate=False):
    output_dir = config["outputDir"]
    reports = collect_reports(config, date)

    if not reports:
        print(yellow(f"[{date}] 작업 이력이 있는 저장소가 없습니다."))
        return 0

    for report in reports:
        file_path = write_report(report, date, output_dir)
        commit_count = len(report["commits"])
        staged_count = len(report["staged_files"])
        unstaged_count = len(report["unstaged_files"])
        untracked_count = len(report.get("untracked_files", []))
        root_label = cyan("[" + report["root_name"] + "]")
        proj_label = bold(report["project_name"])
        print(f"  {root_label} {proj_label}: "
              f"커밋 {green(str(commit_count) + '건')}, staged {yellow(str(staged_count) + '건')}, "
              f"unstaged {yellow(str(unstaged_count) + '건')}, untracked {yellow(str(untracked_count) + '건')} → {dim(file_path)}")

    count = len(reports)
    print(f"\n{green('총 ' + str(count) + '개 프로젝트 리포트 생성 완료')} ({date})")

    if notify_after_generate:
        if not notify(config, date, output_dir):
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
        selected_date = pick_missed_day(result, args.days)
        if not selected_date:
            return 0

        print("")
        exit_code = generate_reports_for_date(config, selected_date, notify_after_generate=args.notify)
        if exit_code == 0:
            output_dir = config["outputDir"]
            print(f"\n{cyan('선택한 날짜 리포트 경로:')} {bold(f'{output_dir}/{selected_date}')}")
            print(f"{dim('다음 단계:')} Codex/Claude로 {output_dir}/{selected_date} 분석 진행")
        return exit_code

    return generate_reports_for_date(config, args.date, notify_after_generate=args.notify)


if __name__ == "__main__":
    sys.exit(main())
