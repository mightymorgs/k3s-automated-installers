#!/usr/bin/env python3
"""Sanitize BWS secret list JSON output.

BWS CLI can emit raw control characters (U+0000-U+001F) inside JSON string
values (e.g., PEM certificates with literal newlines). This breaks jq.

This script does byte-level sanitization: it tracks JSON string boundaries
(unescaped double quotes) and strips control characters only inside strings.
Structural JSON whitespace (newlines between elements) is preserved.
"""
import sys

data = sys.stdin.buffer.read()
out = bytearray()
in_str = False
esc = False

for b in data:
    if esc:
        out.append(b)
        esc = False
        continue
    if b == 92 and in_str:  # backslash inside string
        out.append(b)
        esc = True
        continue
    if b == 34:  # double quote
        in_str = not in_str
    if in_str and b < 32:  # control char inside string — skip
        continue
    out.append(b)

sys.stdout.buffer.write(bytes(out))
