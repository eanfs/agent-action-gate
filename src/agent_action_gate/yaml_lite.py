# SPDX-License-Identifier: Apache-2.0
"""A small YAML subset loader for policy files.

Supported: indentation-based maps, block lists, comments, booleans,
integers, and double-quoted strings. Flow collections, anchors, and
multiline strings are rejected.
"""

from __future__ import annotations

import re


class YamlError(ValueError):
    """The text is not in the supported subset."""


def loads(text: str):
    lines = _tokenize(text)
    if not lines:
        raise YamlError("document is empty")
    value, index = _parse_node(lines, 0, lines[0][1])
    if index != len(lines):
        lineno = lines[index][0]
        raise YamlError(f"line {lineno}: unexpected content")
    return value


def _tokenize(text: str) -> list[tuple[int, int, str]]:
    lines: list[tuple[int, int, str]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if raw.endswith("\r"):
            raw = raw[:-1]
        if "\t" in raw:
            raise YamlError(f"line {lineno}: tabs are not allowed")
        content = _strip_comment(raw, lineno).rstrip()
        if content.strip() == "":
            continue
        indent = len(content) - len(content.lstrip(" "))
        lines.append((lineno, indent, content.strip()))
    return lines


def _strip_comment(line: str, lineno: int) -> str:
    out: list[str] = []
    in_quote = False
    escaped = False
    for ch in line:
        if in_quote:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_quote = False
            continue
        if ch == '"':
            in_quote = True
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    if in_quote:
        raise YamlError(f"line {lineno}: unterminated string")
    return "".join(out)


def _parse_node(lines, index: int, indent: int):
    if index >= len(lines):
        raise YamlError("unexpected end of document")
    lineno, ind, content = lines[index]
    if ind != indent:
        raise YamlError(f"line {lineno}: expected indent {indent}, got {ind}")
    if content.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_map(lines, index, indent)


def _parse_map(lines, index: int, indent: int):
    mapping: dict = {}
    while index < len(lines):
        lineno, ind, content = lines[index]
        if ind < indent:
            break
        if ind > indent:
            raise YamlError(f"line {lineno}: unexpected indent")
        if content.startswith("- "):
            break
        key, rest = _split_key(content, lineno)
        if key in mapping:
            raise YamlError(f"line {lineno}: duplicate key {key}")
        index += 1
        if rest == "":
            if index >= len(lines) or lines[index][1] <= indent:
                mapping[key] = {}
            else:
                child, index = _parse_node(lines, index, lines[index][1])
                mapping[key] = child
        else:
            mapping[key] = _parse_scalar(rest, lineno)
    return mapping, index


def _parse_list(lines, index: int, indent: int):
    items: list = []
    while index < len(lines):
        lineno, ind, content = lines[index]
        if ind != indent or not content.startswith("- "):
            break
        rest = content[2:].strip()
        index += 1
        if rest == "":
            if index >= len(lines):
                raise YamlError(f"line {lineno}: list item is empty")
            child, index = _parse_node(lines, index, lines[index][1])
            items.append(child)
            continue
        if _looks_like_key(rest):
            key, value_src = _split_key(rest, lineno)
            item: dict = {}
            if value_src == "":
                if index >= len(lines) or lines[index][1] <= indent:
                    item[key] = {}
                else:
                    child, index = _parse_node(lines, index, lines[index][1])
                    item[key] = child
            else:
                item[key] = _parse_scalar(value_src, lineno)
            while index < len(lines) and lines[index][1] > indent:
                extra, index = _parse_map(lines, index, lines[index][1])
                overlap = set(item).intersection(extra)
                if overlap:
                    raise YamlError(
                        f"line {lines[index - 1][0]}: duplicate key {sorted(overlap)[0]}"
                    )
                item.update(extra)
            items.append(item)
            continue
        items.append(_parse_scalar(rest, lineno))
    if not items:
        raise YamlError("expected a list item")
    return items, index


def _looks_like_key(text: str) -> bool:
    if text.startswith('"'):
        return False
    try:
        _split_key(text, 0)
    except YamlError:
        return False
    return True


def _split_key(content: str, lineno: int) -> tuple[str, str]:
    in_quote = False
    escaped = False
    for index, ch in enumerate(content):
        if in_quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_quote = False
            continue
        if ch == '"':
            in_quote = True
            continue
        if ch == ":" and (index + 1 == len(content) or content[index + 1] == " "):
            key = content[:index].strip()
            rest = content[index + 1 :].strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
                raise YamlError(f"line {lineno}: invalid key {key!r}")
            return key, rest
    raise YamlError(f"line {lineno}: expected key: value")


def _parse_scalar(raw: str, lineno: int):
    if raw.startswith('"'):
        return _parse_quoted(raw, lineno)
    if raw in {"true", "false"}:
        return raw == "true"
    if raw in {"null", "~"}:
        return None
    if re.fullmatch(r"-?[0-9]+", raw):
        return int(raw)
    if re.fullmatch(r"-?[0-9]+\.[0-9]+", raw):
        raise YamlError(f"line {lineno}: floats are not supported")
    if re.fullmatch(r"[A-Za-z0-9_./+-]+", raw):
        return raw
    raise YamlError(f"line {lineno}: quote this string")


def _parse_quoted(raw: str, lineno: int) -> str:
    if len(raw) < 2 or not raw.endswith('"'):
        raise YamlError(f"line {lineno}: unterminated string")
    body = raw[1:-1]
    out: list[str] = []
    escaped = False
    mapping = {'n': '\n', 't': '\t', '"': '"', '\\': '\\'}
    for ch in body:
        if escaped:
            if ch not in mapping:
                raise YamlError(f"line {lineno}: unknown escape \\{ch}")
            out.append(mapping[ch])
            escaped = False
        elif ch == "\\":
            escaped = True
        else:
            out.append(ch)
    if escaped:
        raise YamlError(f"line {lineno}: unterminated escape")
    return "".join(out)
