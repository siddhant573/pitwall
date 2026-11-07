"""Plain-text board rendering, shared by `pitwall status` and `pitwall sim`."""
from __future__ import annotations

FLAGS = {"box": "🟡", "red": "🔴", "done": "🏁", "green": "🟢"}
NAMES = {"box": "Box box", "red": "Red flag", "done": "Chequered", "green": "Green flag"}


def fmt_age(s: int) -> str:
    s = max(0, int(s))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h{(s % 3600) // 60:02d}"


def counts_line(counts: dict) -> str:
    return " · ".join(f"{FLAGS[k]} {counts.get(k, 0)}" for k in ("box", "red", "done", "green"))


def render_board(board_msg: dict, cursor: int | None = None, width: int = 60) -> str:
    sessions = board_msg.get("sessions") or []
    lines = [counts_line(board_msg.get("counts") or {}), ""]
    if not sessions:
        lines.append("No agent sessions yet. Start one in iTerm2.")
        return "\n".join(lines)
    label_w = max(8, width - 28)
    for i, s in enumerate(sessions):
        state = s.get("state", "")
        mark = "›" if cursor == i else " "
        name = f"{s['title']} — {s.get('label', '')}" if s.get("title") else str(s.get("label", ""))
        label = name[:label_w].ljust(label_w)
        extra = f"waiting {fmt_age(s.get('age_s', 0))}" if state == "box" else NAMES.get(state, state)
        dim = "" if s.get("focusable", True) else "  (no tab)"
        lines.append(f"{mark} {FLAGS.get(state, '?')} {label} {extra}{dim}")
    return "\n".join(lines)
