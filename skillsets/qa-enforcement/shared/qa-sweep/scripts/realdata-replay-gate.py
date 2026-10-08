#!/usr/bin/env python3
"""Fail-closed real production-data replay gate for Pallium data fixes."""

from __future__ import annotations

import argparse
from bisect import bisect_right
import fnmatch
import hashlib
import html
import json
import os
import re
import shlex
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import unquote, unquote_plus, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PATHS_FILE = ROOT / "realdata-paths.json"
REPORT_NAME = "REALDATA-REPLAY.md"
DENYLIST_ENV = "REALDATA_REPLAY_DENYLIST"
DEFAULT_DENYLIST_RELATIVE = Path(".config/realdata-gate/tenant-labels.txt")
HEX_SHA = re.compile(r"^[0-9a-f]{40,64}$", re.I)
HEX_256 = re.compile(r"^[0-9a-f]{64}$", re.I)
IDENTIFIERS = (
    ("ObjectId-like token", re.compile(r"(?<![0-9a-f])[0-9a-f]{24}(?![0-9a-f])", re.I)),
    ("long numeric identifier", re.compile(r"(?<![A-Fa-f0-9])\d{12,}(?![A-Fa-f0-9])")),
    ("SSN-like number", re.compile(r"(?<!\d)\d{3}(?P<separator>[- ])\d{2}(?P=separator)\d{4}(?!\d)")),
    ("labelled SSN field", re.compile(r"\b(?:ssn(?:[\s_-]*number)?|social[\s_-]*security(?:[\s_-]*number)?)\s*[:=]\s*[^\s,;|]+", re.I)),
    ("international phone number", re.compile(r"(?<![A-Za-z0-9])\+\d(?:[\s().-]*\d){8,}(?![A-Za-z0-9])")),
    ("parenthesized phone number", re.compile(r"(?<!\d)\(\d{3}\)\s+\d{3}-\d{4}(?!\d)")),
    ("grouped phone number", re.compile(r"(?<!\d)\d{3}(?P<separator>[-.])\d{3}(?P=separator)\d{4}(?!\d)")),
    ("email address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("labelled personal field", re.compile(r"\b(?:(?:full|personal|first|last|patient|tenant|user|owner|client|contact|clinician|customer|member)[\s_-]*name|contact|email[\s_-]*address|phone(?:[\s_-]*number)?)\s*[:=]\s*[^\s,;|]+", re.I)),
    ("bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}={0,2}", re.I)),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    ("secret assignment", re.compile(r"\b(?:api[_-]?key|key|secret|password)\s*=\s*['\"]?[^\s,'\";]{1,}", re.I)),
)
URI = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s<>\"']+", re.I)
REQUIRED_FIELD_KEYS = (
    "Copy time (UTC)", "Control SHA", "Candidate SHA", "Local copy",
    "Production source", "Privacy", "Blocked rows",
)
REQUIRED_TABLE_KEYS = {
    "goal", "target rows", "control count", "candidate count", "reason", "error class",
}
ARTIFACT_FOOTER_PREFIX = re.compile(
    r"^\s*[-*]?\s*Artifact SHA-256 \(excluding this line\):", re.I
)
ARTIFACT_FOOTER_LINE = re.compile(
    r"^\s*[-*]?\s*Artifact SHA-256 \(excluding this line\):\s*([0-9a-f]{64})\s*$", re.I
)
LABEL_LINE_MARKER = "\ue000"
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
HTML_REFERENCE = re.compile(r"&(?:#[xX][0-9a-fA-F]+;?|#[0-9]+;?|[A-Za-z][A-Za-z0-9]+;?)")
HTML_TAG = re.compile(r'''</?[A-Za-z](?:[^'">]|"[^"]*"|'[^']*')*>''', re.S)
HTML_ATTRIBUTE_VALUE = re.compile(
    r'''(?:^|\s)([^\s=<>/]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))'''
)
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]*)\)", re.S)
MARKDOWN_REFERENCE_DEFINITION = re.compile(r"(?m)^\s{0,3}\[[^\]]+\]:\s*(.+)$")
MARKDOWN_DESTINATION = re.compile(r"^\s*(?:<([^>\r\n]*)>|((?:\\.|[^\s()<>])+))")
URL_SINGLE_ATTRIBUTES = {
    "href", "src", "action", "formaction", "cite", "data", "poster", "xlink:href",
    "manifest", "background", "codebase", "classid", "longdesc", "usemap", "itemid",
}
URL_WHITESPACE_LIST_ATTRIBUTES = {"ping", "archive", "itemtype", "profile"}
URL_SRCSET_ATTRIBUTES = {"srcset", "imagesrcset"}


def validate_report_text(text: str) -> tuple[bool, str, str | None]:
    """Validate report structure, privacy and its footer."""
    denylist_value = os.environ.get(DENYLIST_ENV)
    if denylist_value:
        denylist_path = Path(denylist_value)
        if not denylist_path.is_absolute():
            return False, "private tenant-label deny-list override must be absolute; label check refused", None
    else:
        denylist_path = (Path("~") / DEFAULT_DENYLIST_RELATIVE).expanduser()
        if not denylist_path.is_absolute():
            return False, "REALDATA-REPLAY.md private tenant-label deny-list unavailable; label check refused", None
    try:
        labels = [line.strip() for line in denylist_path.read_text(encoding="utf-8").splitlines()
                  if line.strip()]
    except FileNotFoundError:
        return False, "private tenant-label deny-list missing; label check refused", None
    except (OSError, UnicodeError):
        return False, "REALDATA-REPLAY.md private tenant-label deny-list unavailable; label check refused", None
    if not labels:
        return False, "private tenant-label deny-list is empty; label check refused", None
    label_patterns = [pattern for label in labels for pattern in (
        _private_label_pattern(label), _private_label_pattern(label, cf_as_space=False))]
    if not any(pattern is not None for pattern in label_patterns):
        return False, "private tenant-label deny-list is empty; label check refused", None

    # Check both deletion and word-separator forms so format marks cannot join or split label words.
    label_scan_text = _exclude_gate_owned_label_keys(text)
    normalized_text = [
        _normalize_label_text(label_scan_text, preserve_line_numbers=True),
        _normalize_label_text(label_scan_text, cf_as_space=False, preserve_line_numbers=True),
    ]
    normalized_text.extend(_normalize_nonrendered_label_texts(label_scan_text))
    for line_number, line in enumerate(text.splitlines(), start=1):
        for label, pattern in IDENTIFIERS:
            if pattern.search(line):
                reason = f"REALDATA-REPLAY.md contains disallowed {label} at line {line_number}"
                return False, reason, None
        for match in URI.finditer(line):
            try:
                parsed = urlsplit(match.group(0))
                if parsed.username is not None or parsed.password is not None:
                    reason = f"REALDATA-REPLAY.md contains credentialed URI at line {line_number}"
                    return False, reason, None
            except ValueError:
                reason = f"REALDATA-REPLAY.md contains malformed URI at line {line_number}"
                return False, reason, None

    label_line = _private_label_line(normalized_text, label_patterns)
    if label_line is not None:
        reason = f"REALDATA-REPLAY.md contains disallowed private tenant label at line {label_line}"
        return False, reason, None

    valid, reason, digest = _validate_report_structure_and_digest(text)
    return valid, reason, digest


def _normalize_label_text(text: str, *, cf_as_space: bool = True,
                          preserve_line_numbers: bool = False) -> str:
    if preserve_line_numbers:
        text = HTML_COMMENT.sub(
            lambda match: LABEL_LINE_MARKER * len(re.findall(r"\r\n?|\n", match.group())), text)
        text = re.sub(r"\r\n?|\n", "\n", text)
    else:
        text = HTML_COMMENT.sub("", text)
    text = unicodedata.normalize("NFKC", _unescape_without_source_newlines(text))
    format_replacement = " " if cf_as_space else ""
    text = "".join(format_replacement if unicodedata.category(char) == "Cf" else char
                    for char in text)
    text = re.sub(r"\\(.)", r"\1", text)

    def keep_source_lines(visible: str, source: str) -> str:
        removed_lines = source.count("\n") - visible.count("\n")
        removed_markers = source.count(LABEL_LINE_MARKER) - visible.count(LABEL_LINE_MARKER)
        return visible + LABEL_LINE_MARKER * (max(0, removed_lines) + max(0, removed_markers))

    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)",
                  lambda match: keep_source_lines(match.group(1), match.group(0)), text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)",
                  lambda match: keep_source_lines(match.group(1), match.group(0)), text)
    text = re.sub(r"\[([^\]]+)\]\[[^\]]*\]",
                  lambda match: keep_source_lines(match.group(1), match.group(0)), text)
    text = re.sub(r"<((?:https?://|mailto:)[^\s>]+)>", r"\1", text, flags=re.I)
    text = HTML_TAG.sub(
        lambda match: LABEL_LINE_MARKER * (
            match.group().count("\n") + match.group().count(LABEL_LINE_MARKER)), text)
    text = re.sub(r"[*_`~]", "", text)
    text = text.replace("|", " ")
    return re.sub(r"[^\S\n]+", " ", text)


def _unescape_without_source_newlines(text: str) -> str:
    """Decode HTML references while keeping decoded CR/LF from shifting source lines."""
    def replace_reference(match: re.Match[str]) -> str:
        return re.sub(r"\r\n?|\n", " ", html.unescape(match.group(0)))

    return HTML_REFERENCE.sub(replace_reference, text)


def _url_list_spans(value: str, start: int, *, srcset: bool = False) -> list[tuple[str, int, bool]]:
    if srcset:
        return _srcset_url_spans(value, start)
    spans: list[tuple[str, int, bool]] = []
    for token in re.finditer(r"[^ \t\n\r\f]+", value):
        raw = token.group()
        left_trim = len(raw) - len(raw.lstrip(","))
        url = raw[left_trim:].rstrip(",")
        if url:
            spans.append((url, start + token.start() + left_trim, True))
    return spans


def _decode_url_form_query(value: str) -> str:
    """Decode form-style plus and percent escapes inside a URL query only."""
    query_start = value.find("?")
    fragment_start = value.find("#")
    if query_start < 0 or (fragment_start >= 0 and fragment_start < query_start):
        return value

    query_end = fragment_start if fragment_start >= 0 else len(value)
    query = value[query_start + 1:query_end]
    # Escaped newlines are decoded whitespace, not source-line boundaries.
    query = re.sub(r"(?i)%0d%0a|%0a|%0d", " ", query)
    decoded_query = unquote_plus(query)
    return value[:query_start + 1] + decoded_query + value[query_end:]


def _srcset_url_spans(value: str, start: int) -> list[tuple[str, int, bool]]:
    """Extract URL tokens from srcset syntax without decoding descriptor text."""
    spans: list[tuple[str, int, bool]] = []
    index = 0
    while index < len(value):
        while index < len(value) and (value[index] in " \t\n\r\f" or value[index] == ","):
            index += 1
        if index == len(value):
            break

        url_start = index
        while index < len(value) and value[index] not in " \t\n\r\f":
            index += 1
        url_end = index
        while url_end > url_start and value[url_end - 1] == ",":
            url_end -= 1
        if url_end > url_start:
            spans.append((value[url_start:url_end], start + url_start, True))

        # A trailing comma on the URL token ends a candidate without descriptors.
        if url_end < index:
            continue

        # Consume descriptors up to the candidate separator. Commas inside a
        # data URL are part of the URL token above, before descriptor parsing.
        while index < len(value):
            if value[index] == ",":
                index += 1
                break
            index += 1
    return spans


def _css_escape(value: str, index: int) -> tuple[str, int]:
    """Decode one CSS escape and retain markers for consumed source newlines."""
    next_index = index + 1
    if next_index >= len(value):
        return "\ufffd", next_index
    char = value[next_index]
    if char in "\r\n\f":
        if char == "\r" and next_index + 1 < len(value) and value[next_index + 1] == "\n":
            next_index += 2
        else:
            next_index += 1
        return LABEL_LINE_MARKER if char in "\r\n" else "", next_index
    if char in "0123456789abcdefABCDEF":
        end = next_index
        while end < len(value) and end - next_index < 6 and value[end] in "0123456789abcdefABCDEF":
            end += 1
        codepoint = int(value[next_index:end], 16)
        decoded = ("\ufffd" if codepoint == 0 or codepoint > 0x10FFFF
                   or 0xD800 <= codepoint <= 0xDFFF else chr(codepoint))
        line_marker = ""
        if end < len(value) and value[end] in " \t\r\n\f":
            if value[end] == "\r" and end + 1 < len(value) and value[end + 1] == "\n":
                end += 2
                line_marker = LABEL_LINE_MARKER
            else:
                if value[end] in "\r\n":
                    line_marker = LABEL_LINE_MARKER
                end += 1
        # Escaped CSS newlines are visible whitespace, but are not source lines.
        if decoded in "\r\n\f":
            decoded = " "
        return decoded + line_marker, end
    return char, next_index + 1


def _css_ident_start(char: str) -> bool:
    return char in "-_\\" or char.isalpha() or ord(char) >= 0x80


def _css_ident_char(char: str) -> bool:
    return char in "-_" or char.isalnum() or ord(char) >= 0x80


def _css_consume_ident(value: str, start: int) -> tuple[str, int]:
    chars: list[str] = []
    index = start
    while index < len(value):
        char = value[index]
        if _css_ident_char(char):
            chars.append(char)
            index += 1
        elif char == "\\" and index + 1 < len(value) and value[index + 1] not in "\r\n\f":
            decoded, index = _css_escape(value, index)
            chars.append(decoded)
        else:
            break
    return "".join(chars), index


def _css_string_payload(value: str, opening: int) -> tuple[str, int, int]:
    """Read one CSS string, decoding escapes while retaining source-line markers."""
    quote = value[opening]
    payload_start = opening + 1
    decoded: list[str] = []
    index = payload_start
    while index < len(value):
        char = value[index]
        if char == quote:
            return "".join(decoded), payload_start, index + 1
        if char in "\r\n\f":
            # A literal newline terminates a CSS string token as a bad string.
            return "".join(decoded), payload_start, index
        if char == "\\" and index + 1 < len(value):
            escaped, index = _css_escape(value, index)
            decoded.append(escaped)
            continue
        decoded.append(char)
        index += 1
    return "".join(decoded), payload_start, index


def _css_url_payload(value: str, opening: int) -> tuple[str, int, int] | None:
    """Read a quoted or unquoted CSS URL payload starting at its opening paren."""
    index = opening + 1
    while index < len(value) and value[index] in " \t\r\n\f":
        index += 1
    if index >= len(value) or value[index] == ")":
        return None

    quote = value[index] if value[index] in "\"'" else None
    payload_start = index + 1 if quote else index
    index = payload_start
    decoded: list[str] = []
    while index < len(value):
        char = value[index]
        if quote and char == quote:
            payload_end = index
            index += 1
            while index < len(value) and value[index] in " \t\r\n\f":
                index += 1
            if index < len(value) and value[index] == ")" and decoded:
                return "".join(decoded), payload_start, index + 1
            return None
        if not quote and char == ")":
            while decoded and decoded[-1] in " \t\r\n\f":
                decoded.pop()
            return ("".join(decoded), payload_start, index + 1) if decoded else None
        if char == "\\" and index + 1 < len(value):
            if value[index + 1] in "\r\n\f" or value[index + 1] in "0123456789abcdefABCDEF":
                escaped, index = _css_escape(value, index)
                decoded.append(escaped)
                continue
            decoded.append(value[index + 1])
            index += 2
            continue
        if quote and char in "\r\n\f":
            return None
        decoded.append(char)
        index += 1
    return None


CSS_STRING_URL_FUNCTIONS = {"image-set", "-webkit-image-set", "image"}


def _css_skip_space_and_comments(value: str, index: int) -> int:
    while index < len(value):
        if value[index] in " \t\r\n\f":
            index += 1
        elif value.startswith("/*", index):
            comment_end = value.find("*/", index + 2)
            if comment_end < 0:
                return len(value)
            index = comment_end + 2
        else:
            break
    return index


def _css_url_spans(value: str, start: int, *, stylesheet: bool = False) -> list[tuple[str, int, bool]]:
    """Extract grammar-defined CSS URL values without decoding ordinary strings."""
    spans: list[tuple[str, int, bool]] = []
    index = 0
    blocks: list[tuple[str, str | None]] = []
    while index < len(value):
        if value.startswith("/*", index):
            comment_end = value.find("*/", index + 2)
            index = len(value) if comment_end < 0 else comment_end + 2
            continue
        if value[index] in "\"'":
            decoded, payload_start, end = _css_string_payload(value, index)
            if blocks and blocks[-1][0] == "(" and blocks[-1][1] in CSS_STRING_URL_FUNCTIONS:
                spans.append((decoded, start + payload_start, True))
            index = max(end, index + 1)
            continue
        if stylesheet and value[index] == "@" and not blocks:
            ident, end = _css_consume_ident(value, index + 1)
            if ident.replace(LABEL_LINE_MARKER, "").lower() == "import":
                next_token = _css_skip_space_and_comments(value, end)
                if next_token < len(value) and value[next_token] in "\"'":
                    decoded, payload_start, string_end = _css_string_payload(value, next_token)
                    spans.append((decoded, start + payload_start, True))
                    index = string_end
                    continue
            index = max(end, index + 1)
            continue
        if _css_ident_start(value[index]):
            ident, end = _css_consume_ident(value, index)
            function_name = ident.replace(LABEL_LINE_MARKER, "").lower()
            if function_name == "url" and end < len(value) and value[end] == "(":
                payload = _css_url_payload(value, end)
                if payload is not None:
                    decoded, payload_start, next_index = payload
                    spans.append((decoded, start + payload_start, True))
                    index = next_index
                    continue
            if end < len(value) and value[end] == "(":
                blocks.append(("(", function_name))
                index = end + 1
                continue
            index = max(end, index + 1)
            continue
        char = value[index]
        if char in "([{":
            blocks.append((char, None))
        elif char in ")]}" and blocks:
            expected = { ")": "(", "]": "[", "}": "{" }[char]
            while blocks:
                opening, _ = blocks.pop()
                if opening == expected:
                    break
        index += 1
    return spans


def _css_style_element_url_spans(source: str) -> list[tuple[str, int, bool]]:
    """Extract CSS URL values from style-element bodies with original offsets."""
    spans: list[tuple[str, int, bool]] = []
    content_start: int | None = None
    for tag_match in HTML_TAG.finditer(source):
        name = re.match(r"</?([A-Za-z][^\s/>]*)", tag_match.group())
        if name is None or name.group(1).lower() != "style":
            continue
        if tag_match.group().startswith("</"):
            if content_start is not None:
                spans.extend(_css_url_spans(
                    source[content_start:tag_match.start()], content_start, stylesheet=True))
                content_start = None
        elif content_start is None:
            content_start = tag_match.end()
    if content_start is not None:
        spans.extend(_css_url_spans(source[content_start:], content_start, stylesheet=True))
    return spans


def _normalize_nonrendered_label_texts(text: str) -> list[str]:
    """Scan raw and entity-decoded HTML values without changing rendered boundaries."""
    # Decoded references can reveal tags, but decoded newlines stay spaces so line
    # positions in either source view still correspond to literal source lines.
    spans: list[tuple[str, int, bool]] = []
    html_sources = dict.fromkeys((text, _unescape_without_source_newlines(text)))
    for source in html_sources:
        source_line_starts = [0]
        source_line_starts.extend(match.end() for match in re.finditer(r"\r\n?|\n", source))

        for match in HTML_COMMENT.finditer(source):
            start = match.start() + 4
            line_offset = bisect_right(source_line_starts, start) - 1
            spans.append((source[start:match.end() - 3], line_offset, False))

        for match in HTML_TAG.finditer(source):
            tag = match.group()
            name = re.match(r"</?([A-Za-z][^\s/>]*)", tag)
            if name is None:
                continue
            tag_name = name.group(1).lower()
            attribute_text = tag[name.end():]
            attribute_offset = match.start() + name.end()
            for attribute in HTML_ATTRIBUTE_VALUE.finditer(attribute_text):
                attribute_name = attribute.group(1).lower()
                group = next(index for index in range(2, 5)
                             if attribute.group(index) is not None)
                value = attribute.group(group)
                value_start = attribute_offset + attribute.start(group)
                line_offset = bisect_right(source_line_starts, value_start) - 1
                if (attribute_name in URL_SINGLE_ATTRIBUTES
                        and (attribute_name != "data" or tag_name == "object")):
                    spans.append((value, line_offset, True))
                elif attribute_name in URL_WHITESPACE_LIST_ATTRIBUTES:
                    url_spans = _url_list_spans(value, value_start)
                    spans.extend((url, bisect_right(source_line_starts, start) - 1, decode_url)
                                 for url, start, decode_url in url_spans)
                elif attribute_name in URL_SRCSET_ATTRIBUTES:
                    url_spans = _url_list_spans(value, value_start, srcset=True)
                    spans.extend((url, bisect_right(source_line_starts, start) - 1, decode_url)
                                 for url, start, decode_url in url_spans)
                elif attribute_name == "style":
                    url_spans = _css_url_spans(value, value_start)
                    spans.extend((url, bisect_right(source_line_starts, start) - 1, decode_url)
                                 for url, start, decode_url in url_spans)
                    spans.append((value, line_offset, False))
                else:
                    spans.append((value, line_offset, False))

        for url, start, decode_url in _css_style_element_url_spans(source):
            line_offset = bisect_right(source_line_starts, start) - 1
            spans.append((url, line_offset, decode_url))

    markdown_line_starts = [0]
    markdown_line_starts.extend(item.end() for item in re.finditer(r"\r\n?|\n", text))
    for match in MARKDOWN_LINK.finditer(text):
        payload = match.group(1)
        payload_line = bisect_right(markdown_line_starts, match.start(1)) - 1
        spans.append((payload, payload_line, False))
        destination = MARKDOWN_DESTINATION.match(payload)
        if destination:
            group = 1 if destination.group(1) is not None else 2
            dest_start = match.start(1) + destination.start(group)
            dest_line = bisect_right(markdown_line_starts, dest_start) - 1
            spans.append((destination.group(group), dest_line, True))
    for match in MARKDOWN_REFERENCE_DEFINITION.finditer(text):
        payload = match.group(1)
        payload_line = bisect_right(markdown_line_starts, match.start(1)) - 1
        spans.append((payload, payload_line, False))
        destination = MARKDOWN_DESTINATION.match(payload)
        if destination:
            group = 1 if destination.group(1) is not None else 2
            dest_start = match.start(1) + destination.start(group)
            dest_line = bisect_right(markdown_line_starts, dest_start) - 1
            spans.append((destination.group(group), dest_line, True))

    normalized: list[str] = []
    for value, line_offset, decode_url in spans:
        prefix = LABEL_LINE_MARKER * line_offset
        values = [value]
        if decode_url:
            # Decode hidden URL text too, without treating escaped line breaks as source lines.
            decoded = re.sub(r"(?i)%0d%0a|%0a|%0d", " ", value)
            decoded = unquote(decoded)
            if decoded != value:
                values.append(decoded)
            form_decoded = _decode_url_form_query(value)
            if form_decoded != value and form_decoded not in values:
                values.append(form_decoded)
        for candidate in values:
            normalized.append(_normalize_label_text(
                prefix + candidate, preserve_line_numbers=True))
            normalized.append(_normalize_label_text(
                prefix + candidate, cf_as_space=False, preserve_line_numbers=True))
    return normalized


def _exclude_gate_owned_label_keys(text: str) -> str:
    """Remove only validator-owned key text while preserving report values and line numbers."""
    lines = text.splitlines(keepends=True)
    key_prefix = re.compile(
        r"^(\s*[-*]?\s*)(" + "|".join(re.escape(key) for key in REQUIRED_FIELD_KEYS) + r"):"
    )
    normalized_table_keys = {_normalize_label_text(key).strip().lower()
                             for key in REQUIRED_TABLE_KEYS}
    valid_footers = [index for index, line in enumerate(lines)
                     if ARTIFACT_FOOTER_LINE.fullmatch(line.rstrip("\r\n"))]
    footer_prefixes = [index for index, line in enumerate(lines)
                       if ARTIFACT_FOOTER_PREFIX.match(line)]
    actual_footer = (valid_footers[0] if len(valid_footers) == 1 and len(footer_prefixes) == 1
                     else None)
    table_header = _required_table_header_index(lines, normalized_table_keys)
    output: list[str] = []
    for index, line in enumerate(lines):
        if index == actual_footer:
            output.append("\n" if line.endswith("\n") else "")
            continue
        line = key_prefix.sub(r"\1", line, count=1)
        if index == table_header and "|" in line:
            pieces = line.split("|")
            for cell_index, cell in enumerate(pieces):
                if _normalize_label_text(cell).strip().lower() in normalized_table_keys:
                    pieces[cell_index] = " "
            line = "|".join(pieces)
        output.append(line)
    return "".join(output)


def _required_table_header_index(lines: list[str], required_keys: set[str]) -> int | None:
    for index, line in enumerate(lines[:-1]):
        if "|" not in line:
            continue
        separator_cells = lines[index + 1].strip().strip("|").split("|")
        if not separator_cells or not all(
                re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in separator_cells):
            continue
        header_cells = {_normalize_label_text(cell).strip().lower()
                        for cell in line.strip().strip("|").split("|")}
        if required_keys.issubset(header_cells):
            return index
    return None


def _private_label_pattern(label: str, *, cf_as_space: bool = True) -> re.Pattern[str] | None:
    normalized = _normalize_label_text(label, cf_as_space=cf_as_space).strip()
    words = normalized.split()
    if not words:
        return None
    expression = (r"(?<!\w)(?P<label_start>"
                  + r"\s+".join(re.escape(word) for word in words) + ")"
                  + r"(?!\w)")
    return re.compile(expression, re.I)


def _private_label_line(text: list[str], patterns: list[re.Pattern[str] | None]) -> int | None:
    active_patterns = [pattern for pattern in patterns if pattern is not None]
    rendered_variants: list[tuple[str, list[int]]] = []
    for variant in text:
        visible: list[str] = []
        source_lines: list[int] = []
        source_line = 1
        for char in variant:
            if char == LABEL_LINE_MARKER:
                source_line += 1
                continue
            visible.append(char)
            source_lines.append(source_line)
            if char == "\n":
                source_line += 1
        rendered_variants.append(("".join(visible), source_lines))

    line_number: int | None = None
    for pattern in active_patterns:
        for rendered_text, source_lines in rendered_variants:
            for match in pattern.finditer(rendered_text):
                start = match.start("label_start")
                matched_line = source_lines[start]
                if line_number is None or matched_line < line_number:
                    line_number = matched_line
    return line_number


def git(repo: Path, *args: str, timeout: float = 4) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "git command failed").strip())
    return result.stdout.strip()


def repo_identity(repo: Path, head: str = "HEAD") -> bool:
    if repo.name.lower() == "pallium-app":
        return True
    try:
        remote = git(repo, "remote", "get-url", "origin").strip().lower()
        remote_path = urlsplit(remote).path if "://" in remote else remote
        if "@" in remote and ":" in remote and "://" not in remote:
            remote_path = remote.split(":", 1)[1]
        remote_name = remote_path.rstrip("/").rsplit("/", 1)[-1]
        if remote_name in {"pallium-app", "pallium-app.git"}:
            return True
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError):
        pass
    try:
        package = json.loads(git(repo, "show", f"{head}:package.json"))
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError):
        return False
    return isinstance(package, dict) and package.get("name") == "pallium-app"


def repo_root(start: Path) -> Path | None:
    try:
        return Path(git(start, "rev-parse", "--show-toplevel"))
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return None


def changed_paths(repo: Path, base: str | None, head: str = "HEAD") -> set[str]:
    paths: set[str] = set()
    if base is None:
        base = "refs/remotes/origin/develop"
        git(repo, "rev-parse", "--verify", f"{base}^{{commit}}")
    if base:
        paths.update(filter(None, git(repo, "diff", "--name-only", f"{base}...{head}").splitlines()))
    for args in (("diff", "--name-only", "HEAD"), ("diff", "--cached", "--name-only", "HEAD")):
        paths.update(filter(None, git(repo, *args).splitlines()))
    paths.update(filter(None, git(repo, "ls-files", "--others", "--exclude-standard").splitlines()))
    return paths


def report_ownership_failure(repo: Path, base: str, head: str = "HEAD") -> str | None:
    """Require production-data changes and merge resolutions to precede the report."""
    commit_range = f"{base}..{head}"
    head_blob = git(repo, "rev-parse", "--verify", f"{head}:{REPORT_NAME}")
    base_report_path = git(repo, "ls-tree", "-r", "--name-only", base, "--", REPORT_NAME)
    if REPORT_NAME in base_report_path.splitlines():
        base_blob = git(repo, "rev-parse", "--verify", f"{base}:{REPORT_NAME}")
        if base_blob == head_blob:
            return f"{REPORT_NAME} report inherited from base; replay this change"

    report_owners = set(filter(None, git(
        repo, "log", "--no-merges", "--format=%H", commit_range, "--", REPORT_NAME).splitlines()))

    log = git(repo, "log", "--no-merges", "--format=%H", "--name-only", commit_range)
    commits: list[tuple[str, set[str]]] = []
    current_commit: str | None = None
    current_paths: set[str] = set()
    for line in log.splitlines():
        if re.fullmatch(r"[0-9a-f]{40,64}", line, re.I):
            if current_commit is not None:
                commits.append((current_commit, current_paths))
            current_commit, current_paths = line, set()
        elif line and current_commit is not None:
            current_paths.add(line)
    if current_commit is not None:
        commits.append((current_commit, current_paths))

    merge_commits = git(repo, "rev-list", "--merges", commit_range).splitlines()
    merge_resolution_paths: dict[str, set[str]] = {}
    for merge_commit in merge_commits:
        try:
            resolution_paths = set(filter(None, git(
                repo, "show", "--remerge-diff", "--format=", "--name-only", merge_commit,
                timeout=4).splitlines()))
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                f"cannot inspect merge resolution for {merge_commit[:8]} with --remerge-diff: {exc}") from exc
        merge_resolution_paths[merge_commit] = resolution_paths
        if REPORT_NAME in resolution_paths:
            report_owners.add(merge_commit)

    if not report_owners:
        return f"{REPORT_NAME} report inherited from base; replay this change"

    # rev-list is newest-first; selecting from it avoids path-limited merge
    # history, which can mistake an unchanged inherited report for ownership.
    ordered_commits = git(repo, "rev-list", "--topo-order", commit_range).splitlines()
    report_commit = next((commit for commit in ordered_commits if commit in report_owners), None)
    if report_commit is None:
        raise RuntimeError(f"cannot identify the commit that owns {REPORT_NAME}")

    for commit, paths in commits:
        if not production_paths(paths):
            continue
        result = subprocess.run(["git", "merge-base", "--is-ancestor", commit, report_commit],
                                cwd=repo, text=True, capture_output=True, timeout=4)
        if result.returncode == 1:
            return ("a production-data change postdates REALDATA-REPLAY.md; "
                    f"replay this change (commit {commit[:8]})")
        if result.returncode:
            raise RuntimeError(f"cannot verify production-data commit ancestry for {commit[:8]}")

    for merge_commit, resolution_paths in merge_resolution_paths.items():
        if not production_paths(resolution_paths):
            continue
        result = subprocess.run(["git", "merge-base", "--is-ancestor", merge_commit, report_commit],
                                cwd=repo, text=True, capture_output=True, timeout=4)
        if result.returncode == 1:
            return ("a production-data change postdates REALDATA-REPLAY.md; "
                    f"replay this change (merge {merge_commit[:8]})")
        if result.returncode:
            raise RuntimeError(
                f"cannot verify production-data merge ancestry for {merge_commit[:8]}")
    return None


def production_paths(paths: set[str]) -> set[str]:
    try:
        patterns = json.loads(PATHS_FILE.read_text(encoding="utf-8"))["patterns"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"cannot load reviewed production-data path list: {exc}") from exc
    return {path for path in paths if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)}


def normalized_report_hash(text: str) -> str:
    """Hash report bytes with the digest field omitted to avoid self-reference."""
    lines = text.splitlines(keepends=True)
    valid_footers = [index for index, line in enumerate(lines)
                     if ARTIFACT_FOOTER_LINE.fullmatch(line.rstrip("\r\n"))]
    if len(valid_footers) == 1:
        lines.pop(valid_footers[0])
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def validate_report(repo: Path, head: str) -> tuple[bool, str, str | None]:
    try:
        result = subprocess.run(["git", "show", f"{head}:{REPORT_NAME}"], cwd=repo,
                                capture_output=True, timeout=4)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"cannot read {REPORT_NAME} from reviewed head: {exc}", None
    if result.returncode:
        return False, f"missing {REPORT_NAME} at reviewed head", None
    committed_bytes = result.stdout
    path = repo / REPORT_NAME
    if path.exists():
        try:
            if path.read_bytes() != committed_bytes:
                return False, f"{REPORT_NAME} has uncommitted changes; commit the report before continuing", None
        except OSError as exc:
            return False, f"cannot compare working-tree {REPORT_NAME} with reviewed head: {exc}", None
    try:
        text = committed_bytes.decode("utf-8")
    except UnicodeError as exc:
        return False, f"cannot decode committed {REPORT_NAME}: {exc}", None
    return validate_report_text(text)


def _validate_report_structure_and_digest(text: str) -> tuple[bool, str, str | None]:
    required = {
        "copy time": r"(?im)^\s*[-*]?\s*Copy time \(UTC\):\s*\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|\+00:00)\s*$",
        "control SHA": r"(?im)^\s*[-*]?\s*Control SHA:\s*[0-9a-f]{40,64}\s*$",
        "candidate SHA": r"(?im)^\s*[-*]?\s*Candidate SHA:\s*[0-9a-f]{40,64}\s*$",
        "loopback-only local copy": r"(?im)^\s*[-*]?\s*Local copy:\s*(?:Mac|local Mac)[^\n]*loopback[^\n]*$",
        "read-only production source": r"(?im)^\s*[-*]?\s*Production source:\s*read-only\b[^\n]*$",
        "counts-only privacy": r"(?im)^\s*[-*]?\s*Privacy:\s*counts only;? no (?:row )?(?:IDs|PII)\b[^\n]*$",
        "per-goal counts/reasons/error classes": r"(?is)\|[^\n]*goal[^\n]*\|[^\n]*target[^\n]*\|[^\n]*control[^\n]*\|[^\n]*candidate[^\n]*\|[^\n]*reason[^\n]*\|[^\n]*error class[^\n]*\|",
        "blocked external-call rows": (
            r"(?m)^Blocked rows: (?:\d{1,3}(?:,\d{3})*|\d+) \([^)\r\n]+\).*$"
        ),
    }
    missing = [name for name, pattern in required.items() if not re.search(pattern, text)]
    if "blocked external-call rows" in missing:
        line_number = len(text.splitlines()) + 1
        return False, ("REALDATA-REPLAY.md is missing required blocked external-call rows "
                       f"at line {line_number} (end of report)"), None
    rows = [line for line in text.splitlines() if line.strip().startswith("|")]
    has_result = any(any(cell.strip() and not set(cell.strip()) <= {"-", ":"}
                         for cell in line.strip().strip("|").split("|")) for line in rows[2:])
    if len(rows) < 3 or not has_result:
        missing.append("at least one per-goal result row")
    if missing:
        return False, "REALDATA-REPLAY.md is missing required fields: " + ", ".join(missing), None
    report_lines = text.splitlines(keepends=True)
    footer_prefixes = [index for index, line in enumerate(report_lines)
                       if ARTIFACT_FOOTER_PREFIX.match(line)]
    valid_footers = [index for index, line in enumerate(report_lines)
                     if ARTIFACT_FOOTER_LINE.fullmatch(line.rstrip("\r\n"))]
    if len(footer_prefixes) != 1 or len(valid_footers) != 1:
        if not footer_prefixes:
            line_number = len(text.splitlines()) + 1
            detail = f"is missing its Artifact SHA-256 footer at line {line_number}"
        elif len(footer_prefixes) > 1:
            line_number = footer_prefixes[1] + 1
            detail = f"has an additional Artifact SHA-256 footer at line {line_number}"
        else:
            line_number = footer_prefixes[0] + 1
            detail = f"has an invalid Artifact SHA-256 footer at line {line_number}"
        return False, f"REALDATA-REPLAY.md {detail}", None
    digest_match = ARTIFACT_FOOTER_LINE.fullmatch(report_lines[valid_footers[0]].rstrip("\r\n"))
    assert digest_match is not None
    actual = normalized_report_hash(text)
    if digest_match.group(1).lower() != actual:
        return False, ("REALDATA-REPLAY.md artifact SHA-256 does not match its contents; likely stale footer after formatting. "
                       "Run the repository formatter first, recompute the footer last, and confirm formatting leaves the bytes unchanged"), actual
    return True, "REALDATA-REPLAY.md fields and SHA-256 are valid", actual


def command_action(command: str) -> str | None:
    lower = command.lower()
    if re.search(r"(?:^|[/\\ ])pre-review\.py(?:\s|$)", command):
        return "review"
    if re.search(r"\bhermes-one(?:\.zsh)?\b|\bbb\s+fleet\s+validate\b", lower):
        return "review"
    if re.search(r"\bgh\s+pr\s+(?:ready|merge)\b", lower):
        return "pr"
    if re.search(r"\bgh\s+pr\s+create\b", lower):
        return "pr-create"
    if re.search(r"\b(?:gh\s+release\s+(?:create|edit)|release[- ]request)\b", lower):
        return "release"
    return None


def attached_texts(command: str, cwd: Path) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    attached_paths: list[str] = []
    try:
        args = shlex.split(command)
    except ValueError:
        return texts, attached_paths
    for index, token in enumerate(args):
        if token in {"--evidence", "--body-file", "--notes-file", "--message-file"} and index + 1 < len(args):
            value = args[index + 1]
            evidence = Path(value)
            evidence = evidence if evidence.is_absolute() else cwd / evidence
            attached_paths.append(evidence.name)
            if evidence.is_file():
                try:
                    texts.append(evidence.read_text(encoding="utf-8"))
                except (OSError, UnicodeError):
                    pass
        elif token == "--body" and index + 1 < len(args):
            texts.append(args[index + 1])
        elif token.startswith("--body="):
            texts.append(token.split("=", 1)[1])
    return texts, attached_paths


def cited(command: str, cwd: Path, digest: str) -> bool:
    texts, attached_paths = attached_texts(command, cwd)
    names_report = any(REPORT_NAME in text for text in texts)
    includes_digest = any(digest in text for text in texts)
    direct_report_attachment = REPORT_NAME in attached_paths and includes_digest
    return direct_report_attachment or (names_report and includes_digest)


def report_attached(command: str, cwd: Path, digest: str) -> bool:
    texts, attached_paths = attached_texts(command, cwd)
    return REPORT_NAME in attached_paths and any(digest in text for text in texts)


def release_request_texts(command: str, cwd: Path) -> list[str]:
    texts: list[str] = []
    try:
        args = shlex.split(command)
    except ValueError:
        return texts
    for index, token in enumerate(args):
        if token not in {"--body", "--body-file", "--notes", "--notes-file", "--message-file"} or index + 1 >= len(args):
            continue
        value = args[index + 1]
        if token == "--body":
            texts.append(value)
            continue
        path = Path(value)
        path = path if path.is_absolute() else cwd / path
        if path.is_file():
            try:
                texts.append(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                pass
    return texts


def release_readback_and_rollback_cited(command: str, cwd: Path) -> bool:
    request = "\n".join(release_request_texts(command, cwd))
    has_readback = re.search(r"\bread[- ]?back\b", request, re.I)
    has_offset = re.search(r"\+\s*\d{1,3}\s*(?:min(?:ute)?s?)?\b", request, re.I)
    has_counts = re.search(r"\bcounts?\b", request, re.I)
    rollback_target = re.search(r"\brollback\b[^\n]*(?:\b[0-9a-f]{7,64}\b|\bdpl_[A-Za-z0-9]+\b)",
                                request, re.I)
    return bool(has_readback and has_offset and has_counts and rollback_target)


def github_repo_slug(repo: Path) -> str | None:
    try:
        remote = git(repo, "remote", "get-url", "origin")
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return None
    if remote.startswith("git@github.com:"):
        path = remote.split(":", 1)[1]
    else:
        parsed = urlsplit(remote)
        if (parsed.hostname or "").lower() != "github.com":
            return None
        path = parsed.path.lstrip("/")
    slug = path.removesuffix(".git").strip("/")
    return slug if len(slug.split("/")) == 2 and all(slug.split("/")) else None


def repo_flag(args: list[str]) -> str | None:
    for index, token in enumerate(args):
        if token in {"-R", "--repo"} and index + 1 < len(args):
            return args[index + 1]
        if token.startswith("--repo="):
            return token.split("=", 1)[1]
        if token.startswith("-R") and token != "-R":
            return token[2:]
    return None


def gh_json(result: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    if result.returncode:
        return None
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("files"), list) else None


def logged_in_github_accounts() -> list[str]:
    clean_env = os.environ.copy()
    clean_env.pop("GH_TOKEN", None)
    clean_env.pop("GITHUB_TOKEN", None)
    try:
        result = subprocess.run(["gh", "auth", "status", "--hostname", "github.com"],
                                text=True, capture_output=True, timeout=5, env=clean_env)
    except (OSError, subprocess.TimeoutExpired):
        return []
    status_text = result.stdout + "\n" + result.stderr
    accounts = re.findall(r"(?im)^\s*[✓✔-]?\s*Logged in to github\.com account\s+([^\s(]+)", status_text)
    return list(dict.fromkeys(accounts))


def pull_request_info(repo: Path, command: str) -> dict[str, Any] | None:
    try:
        args = shlex.split(command)
    except ValueError:
        args = []
    reference: str | None = None
    for index in range(max(0, len(args) - 1)):
        if args[index:index + 2] == ["pr", "ready"] or args[index:index + 2] == ["pr", "merge"]:
            if index + 2 < len(args) and not args[index + 2].startswith("-"):
                reference = args[index + 2]
            break
    query = ["gh", "pr", "view"]
    if reference:
        query.append(reference)
    target_repo = repo_flag(args) or github_repo_slug(repo)
    if target_repo:
        query.extend(["--repo", target_repo])
    query.extend(["--json", "body,headRefOid,baseRefOid,files"])
    try:
        result = subprocess.run(query, cwd=repo, text=True, capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        result = None
    data = gh_json(result) if result is not None else None
    if data is not None:
        return data

    clean_env = os.environ.copy()
    clean_env.pop("GH_TOKEN", None)
    clean_env.pop("GITHUB_TOKEN", None)
    for login in logged_in_github_accounts():
        try:
            token_result = subprocess.run(["gh", "auth", "token", "--user", login],
                                          text=True, capture_output=True, timeout=5, env=clean_env)
        except (OSError, subprocess.TimeoutExpired):
            continue
        token = token_result.stdout.strip() if token_result.returncode == 0 else ""
        if not token:
            continue
        account_env = os.environ.copy()
        account_env.pop("GITHUB_TOKEN", None)
        account_env["GH_TOKEN"] = token
        try:
            result = subprocess.run(query, cwd=repo, text=True, capture_output=True,
                                    timeout=5, env=account_env)
        except (OSError, subprocess.TimeoutExpired):
            result = None
        token = ""
        data = gh_json(result) if result is not None else None
        if data is not None:
            return data
    return None


def evaluate(repo: Path, base: str | None, action: str, command: str = "", cwd: Path | None = None,
             head: str = "HEAD") -> tuple[bool, str, set[str], str | None]:
    cwd = cwd or repo
    if not repo_identity(repo, head):
        return True, "not the Pallium app repository", set(), None
    pr_info: dict[str, Any] | None = None
    diff_paths: set[str]
    report_range_base: str
    try:
        if action == "pr":
            pr_info = pull_request_info(repo, command)
            if pr_info is None:
                return False, "cannot read the target PR's changed files; refusing to guess", set(), None
            diff_paths = {str(item.get("path")) for item in pr_info["files"]
                          if isinstance(item, dict) and item.get("path")}
            report_range_base = str(pr_info.get("baseRefOid") or "")
            if not report_range_base:
                return False, "cannot establish the target PR's base commit; refusing to guess", set(), None
            impacted = production_paths(diff_paths)
        elif action == "release":
            production_base = "refs/remotes/origin/main"
            try:
                git(repo, "rev-parse", "--verify", f"{production_base}^{{commit}}")
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                return False, ("cannot resolve production branch refs/remotes/origin/main "
                               "for release diff"), set(), None
            diff_paths = changed_paths(repo, production_base, head)
            report_range_base = production_base
            if base is not None and base != production_base:
                # Explicit bases may broaden the release scope, but must never
                # hide paths changed since production's current branch.
                diff_paths.update(changed_paths(repo, base, head))
            impacted = production_paths(diff_paths)
        else:
            diff_paths = changed_paths(repo, base, head)
            report_range_base = base or "refs/remotes/origin/develop"
            impacted = production_paths(diff_paths)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return False, f"cannot establish the Pallium production-data diff: {exc}", set(), None
    if not impacted:
        return True, "no production-data paths changed", set(), None
    if action == "pr" and str(pr_info.get("headRefOid") or "").lower() != git(repo, "rev-parse", head).lower():
        return False, "run the PR-ready or merge gate from the worktree at the exact target PR head", impacted, None
    valid, reason, digest = validate_report(repo, head)
    if not valid or digest is None:
        return False, reason, impacted, digest
    try:
        ownership_failure = report_ownership_failure(repo, report_range_base, head)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return False, f"cannot establish REALDATA-REPLAY.md ownership: {exc}", impacted, digest
    if ownership_failure:
        return False, ownership_failure, impacted, digest
    if action == "review":
        # pre-review creates the packet that cites the report; Hermes itself must attach it.
        if "pre-review.py" not in command and not report_attached(command, cwd, digest):
            return False, f"Hermes evidence must attach {REPORT_NAME} with its SHA-256", impacted, digest
    elif action in {"pr", "pr-create", "release"}:
        try:
            git(repo, "cat-file", "-e", f"{head}:{REPORT_NAME}")
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            return False, f"{REPORT_NAME} must be committed for PR-ready, merge, or release", impacted, digest
        if action == "release":
            if not release_readback_and_rollback_cited(command, cwd):
                return False, ("release request must name the post-release read-back offset and counts, "
                               "plus a rollback SHA or deployment ID"), impacted, digest
        if action == "pr" and not (REPORT_NAME in str(pr_info.get("body") or "")
                                    and digest in str(pr_info.get("body") or "")):
            return False, f"the current PR body must cite {REPORT_NAME} and its SHA-256", impacted, digest
        if action in {"pr-create", "release"} and not cited(command, cwd, digest):
            return False, f"the PR or release request must cite {REPORT_NAME} and its SHA-256", impacted, digest
    return True, "real production-data replay evidence and citation are present", impacted, digest


def hook() -> int:
    try:
        payload: dict[str, Any] = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                    "permissionDecisionReason": "[realdata-replay-gate] invalid hook payload; review or release denied"}}))
        return 2
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    command = str(tool_input.get("command") or tool_input.get("cmd") or "")
    action = command_action(command)
    if not action:
        return 0
    cwd = Path(str(payload.get("cwd") or payload.get("working_directory") or os.getcwd())).resolve()
    repo = repo_root(cwd)
    if repo is None or not repo_identity(repo):
        return 0
    ok, reason, impacted, digest = evaluate(repo, None, action, command, cwd)
    if ok:
        return 0
    detail = ", ".join(sorted(impacted)) or "diff unknown"
    message = f"[realdata-replay-gate] {reason}; affected paths: {detail}. Complete and cite the read-only Mac loopback replay before review or release."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                "permissionDecisionReason": message}}))
    print(message, file=sys.stderr)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="mode", required=True)
    subs.add_parser("hook")
    check = subs.add_parser("check")
    check.add_argument("--repo", type=Path, required=True)
    check.add_argument("--base")
    check.add_argument("--action", choices=("review", "pr", "pr-create", "release"), default="review")
    check.add_argument("--command", default="pre-review.py")
    check.add_argument("--cwd", type=Path)
    check.add_argument("--head", default="HEAD")
    check.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.mode == "hook":
        return hook()
    repo = repo_root(args.repo.resolve())
    if repo is None:
        print("[realdata-replay-gate] not inside a git worktree", file=sys.stderr)
        return 2
    ok, reason, impacted, digest = evaluate(repo, args.base, args.action, args.command,
                                            args.cwd.resolve() if args.cwd else repo, args.head)
    if args.json:
        print(json.dumps({"allowed": ok, "reason": reason, "affected_paths": sorted(impacted),
                          "artifact": REPORT_NAME if impacted and digest else None, "sha256": digest}))
    else:
        print(f"[realdata-replay-gate] {'ALLOW' if ok else 'DENY'}: {reason}")
        if impacted:
            print("affected paths: " + ", ".join(sorted(impacted)))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
