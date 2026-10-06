#!/usr/bin/env python3
"""Guards firmware/src/web_server.cpp against a route shipping without the
X-Auth-Token check it's supposed to have.

This is exactly the class of bug found in the security review: GET
/api/screenshot.bmp shipped with no auth check even though it can render the
Connectivity screen's on-screen auth token. This script parses each
server.on(...) route registration and, for every route NOT on the explicit
UNAUTHENTICATED_BY_DESIGN allowlist below, requires its handler's token
comparison (`wifi_get_token()`) to appear before the handler's first 200
response -- i.e. the gate actually runs ahead of doing anything useful.

Adding a route to the allowlist is a real security decision (it means the
route is intentionally open) -- do it deliberately, with a comment, not to
silence a failure.

Usage: python tools/check_auth_gated_routes.py
Exit code 0 if every non-allowlisted route is gated, 1 otherwise.
"""
import re
import sys
from pathlib import Path

SRC_PATH = Path(__file__).resolve().parent.parent / "firmware" / "src" / "web_server.cpp"

# (path, method) pairs that are intentionally open -- read-only, and each
# one's handler is documented (in web_server.cpp) as never exposing the
# auth token or any other secret.
UNAUTHENTICATED_BY_DESIGN = {
    ("/", "HTTP_GET"),               # static dashboard HTML, no device data
    ("/api/state", "HTTP_GET"),      # explicitly excludes the token, see build_state_json()
    ("/api/config", "HTTP_GET"),     # labels/current values only, no secret
}

ROUTE_RE = re.compile(r'server\.on\(\s*"([^"]+)"\s*,\s*(HTTP_\w+)\s*,\s*(\w+)\s*\)\s*;')
FUNC_RE_TMPL = r'\b(?:static\s+)?void\s+{name}\s*\([^)]*\)\s*\{{'
LINE_COMMENT_RE = re.compile(r'//[^\n]*')
BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)


def strip_comments(text: str) -> str:
    return LINE_COMMENT_RE.sub("", BLOCK_COMMENT_RE.sub("", text))


def extract_function_body(src: str, name: str) -> str | None:
    m = re.search(FUNC_RE_TMPL.format(name=re.escape(name)), src)
    if not m:
        return None
    depth = 1
    i = m.end()
    start = i
    while i < len(src) and depth:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start:i - 1]


def main() -> int:
    src = SRC_PATH.read_text(encoding="utf-8")
    routes = ROUTE_RE.findall(src)
    if not routes:
        print(f"FAIL: found no server.on(...) routes in {SRC_PATH} -- regex may be stale")
        return 1

    ok = True
    for path, method, handler in routes:
        if (path, method) in UNAUTHENTICATED_BY_DESIGN:
            print(f"OK    {method:10s} {path:24s} (allowlisted open route)")
            continue

        body = extract_function_body(src, handler)
        if body is None:
            ok = False
            print(f"FAIL  {method:10s} {path:24s} -> couldn't locate body of {handler}()")
            continue

        clean = strip_comments(body)
        token_pos = clean.find("wifi_get_token()")
        send200_pos = clean.find("server.send(200")
        gated = token_pos != -1 and (send200_pos == -1 or token_pos < send200_pos)
        if gated:
            print(f"OK    {method:10s} {path:24s} -> {handler}() checks the token first")
        else:
            ok = False
            print(
                f"FAIL  {method:10s} {path:24s} -> {handler}() is not on the open-route allowlist "
                f"and doesn't check wifi_get_token() before its first 200 response"
            )

    if ok:
        print(f"\nOK: all {len(routes)} routes are either allowlisted-open or token-gated")
    else:
        print(
            "\nIf a route above is genuinely meant to be open, add it to "
            "UNAUTHENTICATED_BY_DESIGN in this script with a comment explaining why."
        )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
