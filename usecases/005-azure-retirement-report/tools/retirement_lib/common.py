"""Shared helpers: paths, safe I/O, locking, sanitizing, URL allowlist, dates, ordering."""
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import html
import json
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

TOOL_VERSION = "1.0.0"
SCHEMA_VERSION = 1

UC_DIR = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = UC_DIR / "reports"
TEMPLATE_DIR = UC_DIR / "report-template"
REPO_REL_REPORTS = "usecases/005-azure-retirement-report/reports"

JST = dt.timezone(dt.timedelta(hours=9))
RUN_NAME_RE = re.compile(r"^\d{8}-\d{6}(-\d+)?$")
NOTICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")

MAX_BATCH = 8
MAX_WAVE = 6
MAX_ATTEMPTS = 3


class ToolError(Exception):
    """Error reported to the caller as JSON with a non-zero exit code."""

    def __init__(self, message: str, code: int = 2, **extra: Any):
        super().__init__(message)
        self.code = code
        self.extra = extra


# ---------------------------------------------------------------- time / dates

def now_jst() -> dt.datetime:
    return dt.datetime.now(tz=JST)


def jst_stamp(t: dt.datetime | None = None) -> str:
    return (t or now_jst()).strftime("%Y-%m-%d %H:%M:%S")


def parse_date(v: Any) -> dt.date | None:
    if not isinstance(v, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", v.strip()):
        return None
    try:
        return dt.date.fromisoformat(v.strip())
    except ValueError:
        return None


def add_months(d: dt.date, n: int) -> dt.date:
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_bounds(y: int, m: int) -> tuple[dt.date, dt.date]:
    return dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])


MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})


def month_number(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int) and 1 <= v <= 12:
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s.isdigit() and 1 <= int(s) <= 12:
            return int(s)
        return MONTHS.get(s)
    return None


# ---------------------------------------------------------------- ordering

def id_key(s: Any) -> tuple:
    s = str(s)
    return (0, int(s), "") if s.isdigit() else (1, 0, s)


def ordinal_ignore_case_key(s: str) -> bytes:
    """Approximates .NET StringComparer.OrdinalIgnoreCase (per-char simple upper-casing, UTF-16 order)."""
    up = "".join(c.upper() if len(c.upper()) == 1 else c for c in s)
    return up.encode("utf-16-be")


# ---------------------------------------------------------------- sanitizing

CTRL_RE = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.I)
SAFELINKS_RE = re.compile(r"safelinks\.protection\.outlook\.com", re.I)
SAFELINKS_TOKEN_RE = re.compile(r"\S*safelinks\.protection\.outlook\.com\S*", re.I)
PLACEHOLDER_RE = re.compile(r"<[A-Z_]{3,}>")
REDACTED_EMAIL = "[メールアドレス削除]"
REDACTED_LINK = "[リンク削除]"
REDACTED_ALL = "[機微情報の可能性があるため削除]"


def deep_unescape(s: str) -> str:
    for _ in range(10):
        prev = s
        s = html.unescape(urllib.parse.unquote(s))
        if s == prev:
            break
    return s


def sensitive_kinds(s: str) -> list[str]:
    t = s + "\n" + deep_unescape(s)
    kinds = []
    if EMAIL_RE.search(t):
        kinds.append("email")
    if SAFELINKS_RE.search(t):
        kinds.append("SafeLinks")
    return kinds


def clean_text(v: Any, limit: int) -> str:
    """Plain single-line text, no control chars, no e-mail / SafeLinks, length-capped."""
    if v is None or isinstance(v, (dict, list)):
        return ""
    s = v if isinstance(v, str) else str(v)
    s = CTRL_RE.sub(" ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    s = EMAIL_RE.sub(REDACTED_EMAIL, s)
    s = SAFELINKS_TOKEN_RE.sub(REDACTED_LINK, s)
    if sensitive_kinds(s):
        return REDACTED_ALL
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s


def clean_list(v: Any, limit: int, max_items: int) -> list[str]:
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for x in v:
        if isinstance(x, (str, int, float)) and not isinstance(x, bool):
            t = clean_text(x, limit)
            if t and t not in out:
                out.append(t)
    return out[:max_items]


def html_escape(s: Any) -> str:
    s = "" if s is None else str(s)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&#39;"))


def walk_strings(v: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    """Yields (path, string) for every string value and key; keys are reported as {key#n} (key)."""
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from walk_strings(x, f"{path}[{i}]")
    elif isinstance(v, dict):
        for j, (k, x) in enumerate(v.items(), 1):
            key_hit = bool(sensitive_kinds(str(k)))
            yield f"{path}.{{key#{j}}} (key)", str(k)
            yield from walk_strings(x, f"{path}.{{key#{j}}}" if key_hit else f"{path}.{k}")


# ---------------------------------------------------------------- URL allowlist

ALLOWED_EXACT_HOSTS = {"portal.azure.com", "ms.portal.azure.com", "ai.azure.com", "feedback.azure.com", "azure.github.io"}
GITHUB_PATH_RE = re.compile(r"^/(Azure|Azure-Samples|microsoft|MicrosoftDocs)(/|$)", re.I)
MS_HOST_RE = re.compile(r"(^|\.)(microsoft\.com|aka\.ms)$")
SAFELINKS_HOST_RE = re.compile(r"(^|\.)safelinks\.protection\.outlook\.com$", re.I)


def url_violation(u: Any) -> str | None:
    """Returns None when the URL passes the allowlist, otherwise the violation kind."""
    if not isinstance(u, str) or not u or re.search(r"\s", u):
        return "empty/invalid"
    try:
        p = urllib.parse.urlsplit(u)
        host = (p.hostname or "").lower()
        has_user = p.username is not None or p.password is not None
    except ValueError:
        return "empty/invalid"
    if not p.scheme or not p.netloc or not host:
        return "empty/invalid"
    if SAFELINKS_HOST_RE.search(host):
        return "SafeLinks"
    if p.scheme.lower() != "https":
        return "notHttps"
    if has_user or "@" in p.netloc:
        return "userInfo"
    if MS_HOST_RE.search(host) or host in ALLOWED_EXACT_HOSTS:
        return None
    if host == "github.com" and GITHUB_PATH_RE.match(p.path or ""):
        return None
    return "disallowedHostOrPath"


def normalize_link(u: Any, depth: int = 0) -> str | None:
    """http->https upgrade, SafeLinks unwrapping, then allowlist. Returns the URL or None."""
    if not isinstance(u, str):
        return None
    u = u.strip()
    if u.lower().startswith("http://"):
        u = "https://" + u[7:]
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return None
    if p.hostname and SAFELINKS_HOST_RE.search(p.hostname):
        if depth > 0:
            return None
        real = urllib.parse.parse_qs(p.query).get("url", [None])[0]
        return normalize_link(real, 1)
    if url_violation(u) is not None or sensitive_kinds(u):
        return None
    return u


# ---------------------------------------------------------------- run folder / I/O

def reports_root() -> Path:
    return Path(os.path.realpath(REPORTS_DIR))


def _norm(p: Path | str) -> str:
    return os.path.normcase(os.path.realpath(p))


def resolve_run(name: str) -> Path:
    if not name:
        raise ToolError("--run is required")
    p = Path(name)
    if p.is_absolute() or len(p.parts) > 1:
        if _norm(p.parent) != _norm(reports_root()):
            raise ToolError("run folder must be directly under " + REPO_REL_REPORTS)
        name = p.name
    if not RUN_NAME_RE.match(name):
        raise ToolError("invalid run folder name (expected YYYYMMDD-HHmmss)")
    d = reports_root() / name
    if not d.is_dir():
        raise ToolError(f"run folder not found: {REPO_REL_REPORTS}/{name}")
    if _norm(d) != os.path.normcase(str(d)):
        raise ToolError("run folder must not be a link / junction")
    return d


def ensure_inside(run: Path, target: Path) -> Path:
    t = _norm(target if target.is_absolute() else run / target)
    r = _norm(run)
    if t != r and not t.startswith(r + os.sep):
        raise ToolError("path escapes the run folder")
    return Path(t)


def work_dir(run: Path) -> Path:
    w = run / ".work"
    if w.exists() and _norm(w) != os.path.normcase(str(Path(_norm(run)) / ".work")):
        raise ToolError(".work must not be a link / junction")
    return w


def write_text(run: Path, rel: str | Path, text: str, bom: bool = False) -> Path:
    target = Path(run) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    ensure_inside(run, target)
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, target)
    return target


def dump_json(obj: Any, indent: int | None = 2) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=indent) + ("\n" if indent else "")


def _no_dup_keys(pairs: list[tuple[str, Any]]) -> dict:
    d: dict = {}
    for k, v in pairs:
        if k in d:
            raise ValueError("duplicate JSON key")
        d[k] = v
    return d


def read_json(path: Path, strict: bool = True) -> Any:
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()
    return json.loads(text, object_pairs_hook=_no_dup_keys) if strict else json.loads(text)


def write_json(run: Path, rel: str | Path, obj: Any) -> Path:
    return write_text(run, rel, dump_json(obj))


HIGHLIGHT_INPUT = ".work/highlight.txt"
REVIEW_NOTE_INPUT = ".work/review-note.txt"
MAX_INPUT_BYTES = 16 * 1024


def read_text_input(run: Path, rel: str, required: bool = True) -> str | None:
    """Read agent-authored free text from a fixed, run-scoped file (never from the command line).

    Report-derived text must not pass through shell parsing, so the orchestrator writes it with its file
    tool and the subcommand reads it here. Links, oversized and non-UTF-8 files are rejected.
    """
    target = run / rel
    if not target.exists() and not target.is_symlink():
        if required:
            raise ToolError(f"input file not found: {rel}", next=f"編集ツールで <run>/{rel} にテキストを書いてから再実行する")
        return None
    work_dir(run)
    if target.is_symlink() or not target.is_file() or _norm(target) != os.path.normcase(str(Path(_norm(run)) / rel)):
        raise ToolError(f"{rel} must be a regular file inside the run folder")
    if target.stat().st_size > MAX_INPUT_BYTES:
        raise ToolError(f"{rel} is too large (max {MAX_INPUT_BYTES} bytes)")
    try:
        return target.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ToolError(f"{rel} must be UTF-8 text") from None


class RunLock:
    """Exclusive lock per run, held through an OS file lock (flock / msvcrt) on reports/.<run>.lock.

    The kernel releases the lock when the holding process exits, so a crashed run never blocks later
    commands and a long-running live command is never treated as stale. The file itself is left in place
    (removing it would let two processes lock different inodes) and lives outside the run folder so it
    survives .work removal.
    """

    def __init__(self, run: Path):
        self.path = Path(run).parent / f".{Path(run).name}.lock"
        self.fd: int | None = None
        self.held = False

    def __enter__(self) -> "RunLock":
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _os_lock(fd)
        except OSError:
            os.close(fd)
            raise ToolError(f"another retirement_tool command is running for this run ({self.path.name})")
        self.fd = fd
        self.held = True
        return self

    def release(self) -> None:
        if not self.held:
            return
        self.held = False
        fd, self.fd = self.fd, None
        if fd is None:
            return
        try:
            _os_unlock(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def __exit__(self, *exc: Any) -> None:
        self.release()


if os.name == "nt":
    import msvcrt

    def _os_lock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _os_unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _os_lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _os_unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


# ---------------------------------------------------------------- state

def state_path(run: Path) -> Path:
    return work_dir(run) / "state.json"


def load_state(run: Path) -> dict:
    p = state_path(run)
    if not p.exists():
        raise ToolError("state not found (.work/state.json). Was this run initialized, or already finalized?")
    st = read_json(p)
    if st.get("schemaVersion") != SCHEMA_VERSION:
        raise ToolError("state schemaVersion mismatch: this run was created by an incompatible tool version")
    return st


def save_state(run: Path, st: dict) -> None:
    st["updatedAt"] = jst_stamp()
    write_json(run, ".work/state.json", st)


def log(st: dict, step: str, message: str) -> None:
    st.setdefault("log", []).append({"at": jst_stamp(), "step": step, "message": message})


def snapshot_id(notices: list[dict]) -> str:
    h = hashlib.sha256()
    for n in sorted(notices, key=lambda x: id_key(x["id"])):
        h.update(f"{n['id']}|{n.get('modified', '')}\n".encode())
    return h.hexdigest()[:16]


PHASES = ["initialized", "enumerated", "planned", "collected", "merged",
          "highlighted", "rendered", "reviewed", "finalized"]


def require_phase(st: dict, allowed: Iterable[str], what: str) -> None:
    if st.get("phase") not in set(allowed):
        raise ToolError(f"`{what}` is not allowed in phase '{st.get('phase')}'. Run `status` for the next action.")
