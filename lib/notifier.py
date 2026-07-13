"""텔레그램 알림 모듈 - 리포트 파일을 HTML로 변환하여 텔레그램 메시지로 전송"""

import json
import hashlib
import os
import re
import stat
import sys
import urllib.request

# python3 lib/notifier.py 로 직접 실행할 때만 sys.path 보정
if __name__ == "__main__":
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from lib.colors import (
    cyan,
    dim,
    green,
    red,
    safe_multiline_text,
    safe_terminal_text,
    yellow,
)

MAX_MESSAGE_LENGTH = 4096
MAX_FILE_SIZE_BYTES = 8 * 1024 * 1024
MAX_MESSAGES_PER_FILE = 100

_TELEGRAM_HTML_TOKEN_RE = re.compile(
    r"</?(?:b|code|pre)>|&(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);|.",
    re.DOTALL,
)
_TELEGRAM_HTML_TAG_RE = re.compile(r"</?(b|code|pre)>")


def _message_units(text):
    """Return UTF-16 code units as a conservative Telegram text metric."""
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


def _escape_html(text):
    """HTML 특수문자 이스케이프"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _convert_inline_md(escaped_line):
    """Convert safe, non-crossing inline Markdown to Telegram HTML.

    Code spans are isolated before bold conversion. This intentionally leaves
    bold markers literal when they span across a code token instead of
    producing invalid crossing HTML tags.
    """
    result = []
    cursor = 0
    backtick_run = re.compile(r"`+")
    while cursor < len(escaped_line):
        opening_match = backtick_run.search(escaped_line, cursor)
        if opening_match is None:
            plain = escaped_line[cursor:]
            result.append(re.sub(r"\*\*([^*\n]+?)\*\*", r"<b>\1</b>", plain))
            break

        code_start = opening_match.start()
        fence = opening_match.group(0)
        plain = escaped_line[cursor:code_start]
        result.append(re.sub(r"\*\*([^*\n]+?)\*\*", r"<b>\1</b>", plain))

        closing_pattern = re.compile(rf"(?<!`){re.escape(fence)}(?!`)")
        closing_match = closing_pattern.search(
            escaped_line,
            code_start + len(fence),
        )
        if closing_match is None:
            result.append(escaped_line[code_start:])
            break
        result.append(
            f"<code>{escaped_line[code_start + len(fence):closing_match.start()]}</code>"
        )
        cursor = closing_match.end()
    return "".join(result)


def _md_to_telegram_html(md_text):
    """마크다운을 텔레그램 호환 HTML로 변환"""
    lines = md_text.split("\n")
    result = []
    code_fence = None
    in_table = False

    for line in lines:
        if code_fence is not None:
            if line.strip() == code_fence:
                code_fence = None
                result.append("</pre>")
            else:
                result.append(_escape_html(line))
            continue

        if re.fullmatch(
            r"<!-- daily-code-learn-report:v1:[0-9a-f]{64} -->",
            line.strip(),
        ):
            continue

        fence_match = re.match(r"^(`{3,})([^`]*)$", line)
        if fence_match:
            code_fence = fence_match.group(1)
            in_table = False
            result.append("<pre>")
            continue

        # <details>/<summary>/</details> 태그 제거, 내용만 유지
        if line.strip() in ("<details>", "</details>"):
            in_table = False
            continue
        m = re.match(r"<summary>(.*?)</summary>", line.strip())
        if m:
            in_table = False
            result.append(f"<b>{_escape_html(m.group(1))}</b>")
            continue

        # 수평선 → 구분선
        if re.match(r"^-{3,}\s*$", line):
            in_table = False
            result.append("———")
            continue

        # 테이블 처리
        if "|" in line and re.match(r"^\s*\|", line):
            # 구분선 행(|---|---|) → 건너뜀
            if re.match(r"^\s*\|[\s\-:|]+\|\s*$", line):
                continue
            # 셀 파싱
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not in_table:
                # 헤더행 → 볼드
                in_table = True
                header = " | ".join(cells)
                result.append(f"<b>{_escape_html(header)}</b>")
            else:
                # 데이터행 → 불릿 형태
                row = " | ".join(cells)
                result.append(f"  • {_convert_inline_md(_escape_html(row))}")
            continue
        else:
            in_table = False

        # 제목 → 볼드 (h1~h6)
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            result.append(f"<b>{_convert_inline_md(_escape_html(m.group(2)))}</b>")
            continue

        # 블록인용 → 인용 표시
        m = re.match(r"^>\s?(.*)", line)
        if m:
            result.append(f"  ▎ {_convert_inline_md(_escape_html(m.group(1)))}")
            continue

        # 리스트 → 불릿
        m = re.match(r"^(\s*)-\s+(.*)", line)
        if m:
            indent = "  " * (len(m.group(1)) // 2)
            result.append(f"{indent}• {_convert_inline_md(_escape_html(m.group(2)))}")
            continue

        # 순서 리스트 유지
        m = re.match(r"^(\s*)\d+\.\s+(.*)", line)
        if m:
            indent = "  " * (len(m.group(1)) // 2)
            result.append(f"{indent}{_convert_inline_md(_escape_html(line.strip()))}")
            continue

        # 일반 텍스트
        result.append(_convert_inline_md(_escape_html(line)))

    # 코드블록이 닫히지 않은 경우 보정
    if code_fence is not None:
        result.append("</pre>")

    return "\n".join(result)


def send_telegram_message(bot_token, chat_id, text):
    """Telegram Bot API sendMessage 호출 (HTML 모드)"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            return False
        try:
            response_body = json.load(resp)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        return (
            isinstance(response_body, dict)
            and response_body.get("ok") is True
        )


def _transport_error_label(error):
    """Return useful transport diagnostics without echoing request URLs."""
    error_name = type(error).__name__
    code = getattr(error, "code", None)
    if isinstance(code, int):
        return f"{error_name} (HTTP {code})"
    return error_name


def split_message(text, max_length=MAX_MESSAGE_LENGTH):
    """텍스트를 독립적으로 유효한 HTML 청크로 분할.

    청크 경계에서 열려 있는 Telegram 지원 태그를 닫고 다음
    청크에서 다시 연다. 이 보정 태그까지 max_length에 포함하며,
    HTML 엔티티와 태그 자체는 중간에서 자르지 않는다.
    """
    if max_length <= 0:
        raise ValueError("max_length는 1 이상이어야 합니다.")

    chunks = []
    current_parts = []
    current_length = 0
    has_source_token = False
    # (tag name, exact opening token). The opening token is retained so a
    # future tag with attributes can be reopened without losing information.
    open_tags = []

    def closing_tags(tags):
        return "".join(f"</{name}>" for name, _opening in reversed(tags))

    def opening_tags(tags):
        return "".join(opening for _name, opening in tags)

    for token_match in _TELEGRAM_HTML_TOKEN_RE.finditer(text):
        token = token_match.group(0)
        next_open_tags = list(open_tags)
        tag_match = _TELEGRAM_HTML_TAG_RE.fullmatch(token)

        if tag_match:
            tag_name = tag_match.group(1)
            if token.startswith("</"):
                if not next_open_tags or next_open_tags[-1][0] != tag_name:
                    raise ValueError(f"잘못된 HTML 태그 순서: {token}")
                next_open_tags.pop()
            else:
                next_open_tags.append((tag_name, token))

        while True:
            required_closing = closing_tags(next_open_tags)
            token_length = _message_units(token)
            closing_length = _message_units(required_closing)
            if current_length + token_length + closing_length <= max_length:
                current_parts.append(token)
                current_length += token_length
                open_tags = next_open_tags
                has_source_token = True
                break

            if not has_source_token:
                raise ValueError(
                    "max_length가 HTML 태그와 텍스트를 담기에 너무 작습니다."
                )

            suffix = closing_tags(open_tags)
            chunk = "".join(current_parts) + suffix
            chunks.append(chunk)

            prefix = opening_tags(open_tags)
            current_parts = [prefix] if prefix else []
            current_length = _message_units(prefix)
            has_source_token = False

    if has_source_token:
        chunks.append("".join(current_parts) + closing_tags(open_tags))

    return chunks


def send_file_as_messages(
    bot_token,
    chat_id,
    file_path,
    date,
    *,
    directory_fd=None,
    relative_name=None,
    expected_directory_identity=None,
    expected_file_identity=None,
    expected_content_sha256=None,
):
    """파일 내용을 읽어 HTML 변환 후 분할 메시지로 전송"""
    file_name = relative_name or os.path.basename(file_path)

    try:
        if directory_fd is not None and (
            not relative_name
            or os.path.basename(relative_name) != relative_name
            or relative_name in {".", ".."}
        ):
            raise OSError("안전하지 않은 리포트 파일 이름입니다.")
        if expected_directory_identity is not None:
            if directory_fd is None:
                raise OSError("생성 리포트 디렉터리 정체성을 확인할 수 없습니다.")
            directory_info = os.fstat(directory_fd)
            observed_directory_identity = (
                directory_info.st_dev,
                directory_info.st_ino,
            )
            if observed_directory_identity != expected_directory_identity:
                raise OSError("생성 후 리포트 디렉터리가 교체되었습니다.")
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        open_target = relative_name if directory_fd is not None else file_path
        open_kwargs = (
            {"dir_fd": directory_fd}
            if directory_fd is not None
            else {}
        )
        file_descriptor = os.open(open_target, flags, **open_kwargs)
        try:
            file_info = os.fstat(file_descriptor)
            if not stat.S_ISREG(file_info.st_mode):
                raise OSError("일반 Markdown 파일이 아닙니다.")
            observed_file_identity = (file_info.st_dev, file_info.st_ino)
            if (
                expected_file_identity is not None
                and observed_file_identity != expected_file_identity
            ):
                raise OSError("생성 후 리포트 파일이 교체되었습니다.")
            if file_info.st_size > MAX_FILE_SIZE_BYTES:
                raise OSError(
                    f"Markdown 파일이 {MAX_FILE_SIZE_BYTES} byte 제한을 넘습니다."
                )
            with os.fdopen(file_descriptor, "rb") as f:
                file_descriptor = None
                raw_content = f.read(MAX_FILE_SIZE_BYTES + 1)
            if len(raw_content) > MAX_FILE_SIZE_BYTES:
                raise OSError(
                    f"Markdown 파일이 {MAX_FILE_SIZE_BYTES} byte 제한을 넘습니다."
                )
            content = raw_content.decode("utf-8")
            if (
                expected_content_sha256 is not None
                and hashlib.sha256(raw_content).hexdigest()
                != expected_content_sha256
            ):
                raise OSError("생성 후 리포트 내용이 변경되었습니다.")
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)

        content = safe_multiline_text(content)
        html_content = _md_to_telegram_html(content)
        safe_date = safe_terminal_text(date)
        safe_file_name = safe_terminal_text(file_name)
        header = (
            f"<b>📋 {_escape_html(safe_date)} - "
            f"{_escape_html(safe_file_name)}</b>\n\n"
        )

        # 헤더와 태그 균형 보정에 필요한 문자까지 포함해 최종
        # 전송 단위를 분할한다.
        message_text = header + html_content
        if (
            _message_units(message_text)
            > MAX_MESSAGE_LENGTH * MAX_MESSAGES_PER_FILE
        ):
            raise OSError(
                f"Telegram 메시지가 {MAX_MESSAGES_PER_FILE}개 제한을 넘습니다."
            )
        chunks = split_message(message_text)
        if len(chunks) > MAX_MESSAGES_PER_FILE:
            raise OSError(
                f"Telegram 메시지가 {MAX_MESSAGES_PER_FILE}개 제한을 넘습니다."
            )
    except Exception as error:
        print(red(
            f"  [텔레그램] 변환 실패: {safe_terminal_text(file_name)} - "
            f"{safe_terminal_text(error)}"
        ))
        return False

    for i, chunk in enumerate(chunks):
        try:
            sent = send_telegram_message(bot_token, chat_id, chunk)
        except Exception as e:
            error_label = _transport_error_label(e)
            print(red(
                f"  [텔레그램] 전송 실패: {safe_terminal_text(file_name)} "
                f"(파트 {i + 1}) - {safe_terminal_text(error_label)}"
            ))
            return False
        if not sent:
            print(red(
                f"  [텔레그램] 전송 실패: {safe_terminal_text(file_name)} "
                f"(파트 {i + 1})"
            ))
            return False

    print(green(
        f"  [텔레그램] 전송 완료: {safe_terminal_text(file_name)} "
        f"({len(chunks)}개 메시지)"
    ))
    return True


def notify(config, date, output_dir, file_paths=None):
    """config 설정에 따라 텔레그램으로 리포트 메시지 전송"""
    telegram = config.get("telegram", {})
    if not telegram.get("enabled", False):
        print(yellow("[텔레그램] 비활성화 상태라 전송할 수 없습니다."))
        return False

    bot_token = telegram.get("bot_token")
    chat_id = telegram.get("chat_id")

    if not bot_token or not chat_id:
        print(yellow("[텔레그램] 토큰 또는 chat_id가 설정되지 않았습니다. 전송을 건너뜁니다."))
        return False

    report_dir = os.path.join(output_dir, date)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    report_directory_fd = None
    try:
        report_directory_fd = os.open(report_dir, directory_flags)
        if not stat.S_ISDIR(os.fstat(report_directory_fd).st_mode):
            raise NotADirectoryError(report_dir)
    except OSError as error:
        if report_directory_fd is not None:
            os.close(report_directory_fd)
        print(yellow(
            "[텔레그램] 일반 리포트 디렉토리를 열 수 없습니다: "
            + safe_terminal_text(report_dir)
            + " - "
            + safe_terminal_text(error)
        ))
        return False

    try:
        missing_requested_file = False
        if file_paths is None:
            try:
                names = sorted(os.listdir(report_directory_fd))
            except OSError as error:
                print(red(
                    "[텔레그램] 리포트 목록 읽기 실패: "
                    + safe_terminal_text(error)
                ))
                return False
            selected_files = [
                (os.path.join(report_dir, name), name, None, None, None)
                for name in names
                if name.endswith(".md")
            ]
        else:
            selected_files = []
            report_dir_absolute = os.path.abspath(report_dir)
            for path in sorted(file_paths):
                expected_directory_identity = getattr(
                    path,
                    "report_directory_identity",
                    None,
                )
                expected_file_identity = getattr(
                    path,
                    "report_file_identity",
                    None,
                )
                expected_content_sha256 = getattr(
                    path,
                    "report_content_sha256",
                    None,
                )
                try:
                    path_absolute = os.path.abspath(path)
                    relative_name = os.path.basename(path_absolute)
                    is_direct_child = (
                        os.path.dirname(path_absolute) == report_dir_absolute
                    )
                    file_info = os.stat(
                        relative_name,
                        dir_fd=report_directory_fd,
                        follow_symlinks=False,
                    )
                    is_regular = stat.S_ISREG(file_info.st_mode)
                    directory_info = os.fstat(report_directory_fd)
                    observed_directory_identity = (
                        directory_info.st_dev,
                        directory_info.st_ino,
                    )
                    artifact_directory_matches = (
                        expected_directory_identity is None
                        or observed_directory_identity
                        == expected_directory_identity
                    )
                except (OSError, TypeError, ValueError):
                    is_direct_child = False
                    is_regular = False
                    artifact_directory_matches = False
                    relative_name = ""
                if (
                    not str(path).endswith(".md")
                    or not is_direct_child
                    or not is_regular
                    or not artifact_directory_matches
                ):
                    print(red(
                        "[텔레그램] 요청한 리포트 파일을 읽을 수 없습니다: "
                        + safe_terminal_text(path)
                    ))
                    missing_requested_file = True
                    continue
                selected_files.append((
                    path,
                    relative_name,
                    expected_directory_identity,
                    expected_file_identity,
                    expected_content_sha256,
                ))

        if not selected_files:
            print(yellow(
                "[텔레그램] 전송할 .md 파일이 없습니다: "
                + safe_terminal_text(report_dir)
            ))
            return False

        print(f"\n{cyan(f'[텔레그램] {len(selected_files)}개 파일 전송 시작...')}")
        ok = True
        for (
            file_path,
            relative_name,
            expected_directory_identity,
            expected_file_identity,
            expected_content_sha256,
        ) in selected_files:
            if not send_file_as_messages(
                bot_token,
                chat_id,
                file_path,
                date,
                directory_fd=report_directory_fd,
                relative_name=relative_name,
                expected_directory_identity=expected_directory_identity,
                expected_file_identity=expected_file_identity,
                expected_content_sha256=expected_content_sha256,
            ):
                ok = False
        return ok and not missing_requested_file
    finally:
        os.close(report_directory_fd)


def notify_file(file_path, date):
    """단일 파일을 텔레그램으로 전송 (스킬에서 호출용)"""
    from lib.config import load_config

    config = load_config()
    telegram = config.get("telegram", {})
    if not telegram.get("enabled", False):
        print(dim("[텔레그램] 비활성화 상태입니다."))
        return False

    bot_token = telegram.get("bot_token")
    chat_id = telegram.get("chat_id")

    if not bot_token or not chat_id:
        print(yellow("[텔레그램] 토큰 또는 chat_id가 설정되지 않았습니다."))
        return False

    if not os.path.isfile(file_path):
        print(red(
            "[텔레그램] 일반 파일이 아닙니다: "
            + safe_terminal_text(file_path)
        ))
        return False

    return send_file_as_messages(bot_token, chat_id, file_path, date)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("사용법: python3 lib/notifier.py <파일경로> <날짜>")
        sys.exit(1)

    sys.exit(0 if notify_file(sys.argv[1], sys.argv[2]) else 1)
