"""Process launching with a retry for transient 'access denied' errors.

On Windows, launching a freshly used executable can fail once with PermissionError (WinError 5),
typically while security software scans it. It succeeded on the next try in testing.
"""
from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def retry_on_permission(fn: Callable[[], T], attempts: int = 3, delay: float = 1.5,
                        sleep: Callable[[float], None] = time.sleep) -> T:
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            sleep(delay)
    raise AssertionError("unreachable")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return retry_on_permission(lambda: subprocess.run(cmd, **kw))


def popen(cmd: list[str], **kw) -> subprocess.Popen:
    return retry_on_permission(lambda: subprocess.Popen(cmd, **kw))
