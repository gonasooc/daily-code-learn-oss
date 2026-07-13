"""터미널 출력 색상 유틸리티 (ANSI escape codes)."""

import os
import sys

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"

_VISIBLE_CONTROL_ESCAPES = {
    "\t": r"\t",
    "\n": r"\n",
    "\r": r"\r",
}


def _is_unsafe_unicode_format(code_point):
    """Return whether an invisible Unicode control can spoof displayed text."""
    return (
        code_point == 0x061C
        or 0x200B <= code_point <= 0x200F
        or 0x2028 <= code_point <= 0x202E
        or 0x2060 <= code_point <= 0x206F
        or code_point == 0xFEFF
        or 0xFFF9 <= code_point <= 0xFFFB
        or 0xE0000 <= code_point <= 0xE007F
    )


def _unicode_escape(code_point):
    if code_point <= 0xFFFF:
        return f"\\u{code_point:04x}"
    return f"\\U{code_point:08x}"


def _safe_text(value, preserve=frozenset()):
    result = []
    for character in str(value):
        if character in preserve:
            result.append(character)
            continue

        visible_escape = _VISIBLE_CONTROL_ESCAPES.get(character)
        if visible_escape is not None:
            result.append(visible_escape)
            continue

        code_point = ord(character)
        if code_point < 0x20 or 0x7F <= code_point <= 0x9F:
            result.append(f"\\x{code_point:02x}")
        elif 0xDC80 <= code_point <= 0xDCFF:
            # os.fsdecode()의 surrogateescape 표현을 원래 바이트 형태로 표시한다.
            result.append(f"\\x{code_point - 0xDC00:02x}")
        elif 0xD800 <= code_point <= 0xDFFF:
            result.append(f"\\u{code_point:04x}")
        elif _is_unsafe_unicode_format(code_point):
            result.append(_unicode_escape(code_point))
        else:
            result.append(character)
    return "".join(result)


def safe_terminal_text(value):
    """외부 입력의 터미널 제어문자를 화면에 보이는 문자열로 바꾼다.

    저장소 이름과 경로는 운영체제에서 제어문자를 포함할 수 있다. 그대로
    출력하면 줄을 위조하거나 ANSI 명령을 실행할 수 있으므로 C0/C1과 방향
    제어문자, Unicode 줄 구분자, 잘못된 파일명 바이트를 이스케이프한다.
    """
    return _safe_text(value)


def safe_multiline_text(value):
    """Preserve diff line/tab structure while neutralizing display controls."""
    return _safe_text(value, preserve=frozenset({"\n", "\t"}))


def supports_color(stream=None, environ=None):
    """현재 출력 환경에서 ANSI 색상을 사용해도 되는지 반환한다.

    ``FORCE_COLOR``는 TTY 검사와 ``NO_COLOR``를 덮어쓴다. 다만 값이
    ``0``, ``false``, ``no``이면 명시적으로 색상을 비활성화한다.
    """
    if environ is None:
        environ = os.environ

    if "FORCE_COLOR" in environ:
        value = str(environ.get("FORCE_COLOR", "")).strip().lower()
        return value not in {"0", "false", "no"}

    if "NO_COLOR" in environ:
        return False

    if environ.get("TERM", "").lower() == "dumb":
        return False

    if stream is None:
        stream = sys.stdout

    try:
        return bool(stream.isatty())
    except (AttributeError, OSError):
        return False


def _style(text, code, *, stream=None, environ=None):
    value = str(text)
    if not supports_color(stream=stream, environ=environ):
        return value
    return f"{code}{value}{RESET}"


def green(text, *, stream=None, environ=None):
    return _style(text, GREEN, stream=stream, environ=environ)


def red(text, *, stream=None, environ=None):
    return _style(text, RED, stream=stream, environ=environ)


def yellow(text, *, stream=None, environ=None):
    return _style(text, YELLOW, stream=stream, environ=environ)


def blue(text, *, stream=None, environ=None):
    return _style(text, BLUE, stream=stream, environ=environ)


def cyan(text, *, stream=None, environ=None):
    return _style(text, CYAN, stream=stream, environ=environ)


def magenta(text, *, stream=None, environ=None):
    return _style(text, MAGENTA, stream=stream, environ=environ)


def bold(text, *, stream=None, environ=None):
    return _style(text, BOLD, stream=stream, environ=environ)


def dim(text, *, stream=None, environ=None):
    return _style(text, DIM, stream=stream, environ=environ)
