#!/usr/bin/env python3
"""Turn a Claude Code session transcript (.jsonl) into readable Markdown.

The transcript is an append-only event log, not a conversation: tool calls,
results, thinking signatures and UI bookkeeping are interleaved with the actual
messages. This reassembles the readable part in order — what was asked, what was
answered, and which tools ran in between — and keeps tool output at a length a
person can actually scan.

Secrets are redacted on the way out. The log contains whatever scrolled through a
terminal, and an exported file is a file that gets shared.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

# Anything shaped like a credential, whatever surrounded it in the log.
_REDACTIONS = (
    (re.compile(r"(sk-or-v1-)[A-Za-z0-9_\-]{12,}"), r"\1<redacted>"),
    (re.compile(r"(sk-[A-Za-z0-9]{4})[A-Za-z0-9_\-]{16,}"), r"\1<redacted>"),
    (re.compile(r"(pa-)[A-Za-z0-9_\-]{16,}"), r"\1<redacted>"),
    (re.compile(r"((?:API_KEY|TOKEN|SECRET|PASSWORD)\s*[=:]\s*)(\S{8,})",
                re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(Bearer\s+)\S{12,}"), r"\1<redacted>"),
)

# Injected UI scaffolding that is not part of what anyone said.
_SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>",
                              re.DOTALL | re.IGNORECASE)
_COMMAND_NOISE = re.compile(r"<(command-name|command-message|command-args|"
                            r"local-command-stdout)>.*?</\1>", re.DOTALL)


def clean(text: str) -> str:
    text = _SYSTEM_REMINDER.sub("", text or "")
    text = _COMMAND_NOISE.sub("", text)
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text.strip()


def fence(text: str, language: str = "") -> str:
    """Wrap in a fence that cannot be broken by backticks inside the text."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    bar = "`" * max(3, longest + 1)
    return f"{bar}{language}\n{text}\n{bar}"


def shorten(text: str, limit: int) -> str:
    text = text.rstrip()
    if limit <= 0 or len(text) <= limit:
        return text
    head = text[: int(limit * 0.7)].rstrip()
    tail = text[-int(limit * 0.2):].lstrip()
    dropped = len(text) - len(head) - len(tail)
    return f"{head}\n\n… [{dropped:,} characters omitted] …\n\n{tail}"


def result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "image":
                    parts.append("[image returned]")
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return "" if content is None else str(content)


def describe_call(name: str, payload: dict) -> tuple[str, str]:
    """A one-line label for a tool call, plus the body worth showing."""
    if name == "Bash":
        return payload.get("description") or "shell", payload.get("command", "")
    if name in {"Read", "Write", "Edit"}:
        target = payload.get("file_path", "")
        if name == "Write":
            return f"write {target}", payload.get("content", "")
        if name == "Edit":
            old = payload.get("old_string", "")
            new = payload.get("new_string", "")
            return f"edit {target}", f"- {old}\n---\n+ {new}"
        return f"read {target}", ""
    if name == "Grep":
        return f"grep {payload.get('pattern', '')}", ""
    label = payload.get("description") or payload.get("query") or ""
    return label or name, json.dumps(payload, indent=2)[:2000]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--max-result", type=int, default=1400,
                        help="characters of tool output to keep (0 = all)")
    parser.add_argument("--max-input", type=int, default=1800,
                        help="characters of tool input to keep (0 = all)")
    parser.add_argument("--no-tools", action="store_true",
                        help="conversation only, no tool calls or results")
    args = parser.parse_args()

    out: list[str] = []
    calls: dict[str, str] = {}
    turns = tools = 0
    started = ended = ""

    for line in args.transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") not in {"user", "assistant"}:
            continue

        stamp = event.get("timestamp", "")
        if stamp:
            started = started or stamp
            ended = stamp

        message = event.get("message") or {}
        role = message.get("role")
        content = message.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")

            if kind == "text":
                body = clean(block.get("text", ""))
                if not body:
                    continue
                turns += 1
                who = "User" if role == "user" else "Claude"
                out.append(f"\n## {who}\n\n{body}\n")

            elif kind == "tool_use" and not args.no_tools:
                tools += 1
                name = block.get("name", "tool")
                label, body = describe_call(name, block.get("input") or {})
                calls[block.get("id", "")] = name
                out.append(f"\n<details>\n<summary><b>{name}</b> — {clean(label)}</summary>\n")
                if body:
                    language = "bash" if name == "Bash" else ""
                    out.append("\n" + fence(clean(shorten(body, args.max_input)), language) + "\n")

            elif kind == "tool_result" and not args.no_tools:
                body = clean(result_text(block.get("content")))
                if body:
                    out.append("\n**Result:**\n\n"
                               + fence(shorten(body, args.max_result)) + "\n")
                out.append("\n</details>\n")

            elif kind == "image":
                out.append("\n> *(image returned — omitted from export)*\n")

    def when(value: str) -> str:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            return value or "unknown"

    header = [
        "# Atreides Archive — full session transcript",
        "",
        f"Exported from `{args.transcript.name}`.",
        "",
        f"- **Session started:** {when(started)}",
        f"- **Last message:** {when(ended)}",
        f"- **Messages:** {turns}",
        f"- **Tool calls:** {tools}",
        "",
        ("Conversation only — tool calls and their output are omitted. "
         "Credentials are redacted."
         if args.no_tools else
         "Tool calls are collapsed — click one to see its command and output. "
         "Long outputs are abridged; credentials are redacted."),
        "",
        "---",
    ]
    args.output.write_text("\n".join(header) + "\n".join(out) + "\n", encoding="utf-8")
    size = args.output.stat().st_size
    print(f"wrote {args.output}  ({size / 1024:.0f} KB, {turns} messages, {tools} tool calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
