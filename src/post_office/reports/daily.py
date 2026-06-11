from __future__ import annotations

from datetime import datetime

from post_office.models import Message


def render_daily_report(
    messages: list[Message],
    *,
    window_start: datetime,
    window_end: datetime,
) -> str:
    lines = [
        "Post Office daily report",
        f"Window: {window_start.isoformat()} - {window_end.isoformat()}",
        f"Messages: {len(messages)}",
        "",
    ]
    current_chat: tuple[str, str] | None = None
    for message in messages:
        chat_key = (message.source.value, message.chat_id)
        if chat_key != current_chat:
            current_chat = chat_key
            chat_label = message.chat_name or message.chat_id
            lines.extend(["", f"## {message.source.value}: {chat_label}"])
        sender = message.sender_name or message.sender_id
        text = message.text.strip() or "[non-text message]"
        lines.append(f"[{message.timestamp:%H:%M}] {sender}: {text}")
    lines.append("")
    return "\n".join(lines)
