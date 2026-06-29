"""터미널 출력 색상 유틸리티 (ANSI escape codes)"""

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"


def green(text):
    return f"{GREEN}{text}{RESET}"


def red(text):
    return f"{RED}{text}{RESET}"


def yellow(text):
    return f"{YELLOW}{text}{RESET}"


def blue(text):
    return f"{BLUE}{text}{RESET}"


def cyan(text):
    return f"{CYAN}{text}{RESET}"


def magenta(text):
    return f"{MAGENTA}{text}{RESET}"


def bold(text):
    return f"{BOLD}{text}{RESET}"


def dim(text):
    return f"{DIM}{text}{RESET}"
