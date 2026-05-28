#!/usr/bin/env python3
"""Generate docs/smoke-test.html — a clickable checklist for all registered
agent tools. Each link opens the LocalLLM UI at http://localhost:3001 with the
prompt pre-filled (see the ?prompt= handler in gemma-web/index.html), ready to
hit send.

Run: python3 scripts/build_smoke_test.py
"""

from __future__ import annotations

import html as html_lib
from pathlib import Path
from urllib.parse import quote

UI_URL = "http://localhost:3001"

# Badges: r=risky (confirmation gate), p=needs macOS permission, f=needs a file
GROUPS: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    (
        "Web & knowledge",
        "🌐",
        [
            (
                "google_search",
                "Search the web for today's top news headline.",
                "",
            ),
            (
                "web_fetch",
                "Fetch https://example.com and tell me what it says.",
                "",
            ),
            (
                "get_current_datetime",
                "What's the exact current date, time, and timezone?",
                "",
            ),
            (
                "recall",
                "Use the recall tool to find what my ingested documents say about gemma.",
                "f",
            ),
        ],
    ),
    (
        "Files & data — read",
        "📄",
        [
            (
                "read_file",
                "Read PROGRESS.md and summarize the most recent entry.",
                "",
            ),
            ("list_dir", "List the files in the current directory.", ""),
            ("find_file", "Find all files matching *.py in this project.", ""),
            (
                "grep_search",
                "Search the project for the pattern 'register_tool'.",
                "",
            ),
            (
                "diff_files",
                "Show a unified diff between .prettierignore and .gitignore.",
                "",
            ),
            (
                "read_csv",
                "Create a CSV file smoke.csv with columns a,b and two rows, then read it back as a table.",
                "",
            ),
            (
                "json_query",
                'From the JSON {"users":[{"name":"Ada"}]}, extract users[0].name using json_query.',
                "",
            ),
            ("read_pdf", "Extract the text from the PDF at <path>.", "f"),
            (
                "read_word",
                "Read the Word document at <path> and summarize it.",
                "f",
            ),
            (
                "read_excel",
                "Read the spreadsheet at <path> and list the sheet names.",
                "f",
            ),
            ("read_ics", "Parse the events in the .ics file at <path>.", "f"),
            (
                "sqlite_query",
                "Run SELECT name FROM sqlite_master on the database at <path>.",
                "rf",
            ),
        ],
    ),
    (
        "Files & data — write / modify",
        "✍️",
        [
            (
                "write_file",
                "Create a file smoketest.txt containing 'hello world'.",
                "r",
            ),
            (
                "append_file",
                "Append the line 'second line' to smoketest.txt.",
                "r",
            ),
            (
                "edit_file",
                "In smoketest.txt, replace 'hello' with 'hi'.",
                "r",
            ),
            (
                "move_file",
                "Rename smoketest.txt to smoketest2.txt.",
                "r",
            ),
            (
                "delete_file",
                "Delete smoketest2.txt (move it to Trash).",
                "r",
            ),
            (
                "sqlite_exec",
                "Create a SQLite database smoke.db with a table t(x INTEGER) and insert the value 1.",
                "r",
            ),
            (
                "write_pdf",
                "Create a PDF report.pdf containing the text 'Smoke test report'.",
                "r",
            ),
            (
                "write_word",
                "Create a Word document report.docx with a heading 'Smoke Test'.",
                "r",
            ),
            (
                "write_excel",
                "Create an Excel file report.xlsx with a sheet 'Data' and a couple of cells.",
                "r",
            ),
        ],
    ),
    (
        "Shell & code",
        "💻",
        [
            ("shell", "Run the shell command 'uname -a'.", "r"),
            (
                "python_interpreter",
                "Use Python to compute the 20th Fibonacci number.",
                "r",
            ),
        ],
    ),
    (
        "Git & dev CLIs",
        "🔧",
        [
            ("git_status", "Show the git status of this repository.", ""),
            ("git_log", "Show the last 5 git commits.", ""),
            ("git_diff", "Show the current git diff vs HEAD.", ""),
            (
                "gh_run",
                "List the 3 most recent GitHub Actions runs using gh run list.",
                "r",
            ),
            (
                "aws_run",
                "Run 'aws sts get-caller-identity'.",
                "r",
            ),
            (
                "hf_run",
                "Run the Hugging Face CLI command 'huggingface-cli whoami'.",
                "r",
            ),
            (
                "http_request",
                "Make a GET request to https://httpbin.org/get and show the response.",
                "r",
            ),
        ],
    ),
    (
        "System, clipboard, audio, screen",
        "🖥️",
        [
            (
                "system_info",
                "What's my CPU, RAM, and disk usage right now?",
                "",
            ),
            (
                "notify",
                "Send a macOS notification titled 'Smoke test' saying 'hello'.",
                "",
            ),
            ("say", "Say out loud: testing one two three.", ""),
            (
                "clipboard_copy",
                "Copy the text 'smoke-test-123' to my clipboard.",
                "",
            ),
            (
                "clipboard_paste",
                "What's currently on my clipboard?",
                "r",
            ),
            ("screenshot", "Take a screenshot of my screen.", "r"),
        ],
    ),
    (
        "Scheduling",
        "⏰",
        [
            ("list_crons", "List my cron jobs.", ""),
            (
                "create_cron",
                "Create a cron job named 'smoke' that runs 'echo hi' every day at 9am.",
                "r",
            ),
            ("delete_cron", "Delete the cron job named 'smoke'.", "r"),
            ("list_scheduled_tasks", "List my scheduled tasks.", ""),
            (
                "create_scheduled_task",
                "Schedule a task named 'smoke' to run the prompt 'say hi' daily at 9am.",
                "r",
            ),
        ],
    ),
    (
        "macOS personal (first use prompts for permission)",
        "📇",
        [
            (
                "calendar_list",
                "What's on my calendar for the next 7 days?",
                "p",
            ),
            (
                "calendar_create",
                "Add a calendar event 'Smoke Test Lunch' on 6/1/2026 at 12:00.",
                "rp",
            ),
            ("reminders_list", "List my open reminders.", "p"),
            (
                "reminders_create",
                "Add a reminder to 'call the bank'.",
                "rp",
            ),
            (
                "notes_search",
                "Search my Apple Notes for the word 'grocery'.",
                "p",
            ),
            (
                "notes_create",
                "Create an Apple Note titled 'Smoke Test' with body 'it works'.",
                "rp",
            ),
            (
                "search_contacts",
                "Look up the contact named 'Kyla' in my Contacts.",
                "p",
            ),
            (
                "contacts_create",
                "Create a contact named 'Test Person' with email test@example.com.",
                "rp",
            ),
            (
                "messages_read",
                "Show my 5 most recent iMessages. (Needs Full Disk Access for the bridge.)",
                "rp",
            ),
            (
                "send_message",
                "Send an iMessage to <your own number> saying 'smoke test'.",
                "rp",
            ),
            (
                "mail_compose",
                "Draft an email to test@example.com, subject 'Smoke test', body 'hello'. (Draft only — never auto-sends.)",
                "rp",
            ),
        ],
    ),
    (
        "On-device multimodal (first run loads a model)",
        "🖼️",
        [
            ("generate_image", "Generate an image of a red bicycle.", "r"),
            (
                "describe_image",
                "Describe the image at <path/to/image.png>.",
                "f",
            ),
            (
                "ocr_image",
                "Extract the text from the image at <path/to/screenshot.png>.",
                "f",
            ),
            (
                "transcribe",
                "Transcribe the audio file at <path/to/clip.wav>.",
                "f",
            ),
        ],
    ),
]


STYLE = """\
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 15px; line-height: 1.55; color: #1a1a2e;
      background: #f4f6fb; padding: 32px 20px 80px;
    }
    .wrap { max-width: 980px; margin: 0 auto; }
    header {
      background: #fff; border-radius: 12px; padding: 28px 32px;
      box-shadow: 0 2px 20px rgba(0,0,0,0.06); margin-bottom: 24px;
    }
    h1 { font-size: 1.7rem; font-weight: 700; color: #0f172a; }
    .lede { color: #475569; margin-top: 6px; }
    .legend { margin-top: 14px; color: #475569; font-size: 0.92em; }
    .legend code { background: none; padding: 0; color: inherit; font-weight: 600; }
    .group {
      background: #fff; border-radius: 12px; padding: 18px 24px;
      box-shadow: 0 2px 20px rgba(0,0,0,0.05); margin-bottom: 18px;
    }
    .group h2 {
      font-size: 1.1rem; font-weight: 600; color: #1e3a5f;
      margin: 0 0 10px; padding-bottom: 8px; border-bottom: 2px solid #e2e8f0;
    }
    .row {
      display: grid; grid-template-columns: 200px 1fr auto;
      gap: 12px; align-items: center;
      padding: 10px 0; border-bottom: 1px dashed #eef2f7;
    }
    .row:last-child { border-bottom: none; }
    .tool {
      font-family: "SF Mono", "Fira Code", monospace; font-weight: 600;
      color: #0f5132; font-size: 0.95em;
    }
    .badges { display: inline-flex; gap: 4px; margin-left: 6px; }
    .badge {
      display: inline-block; padding: 1px 6px; border-radius: 10px;
      font-size: 0.72em; font-weight: 600; line-height: 1.6;
    }
    .badge.r { background: #fef3c7; color: #92400e; }
    .badge.p { background: #dbeafe; color: #1e3a8a; }
    .badge.f { background: #f3e8ff; color: #6b21a8; }
    .prompt {
      font-family: "SF Mono", "Fira Code", monospace; font-size: 0.86em;
      color: #334155; background: #f8fafc; padding: 6px 10px; border-radius: 6px;
      word-break: break-word;
    }
    a.open {
      display: inline-block; background: #2563eb; color: #fff;
      padding: 6px 14px; border-radius: 8px; text-decoration: none;
      font-weight: 600; font-size: 0.85em; white-space: nowrap;
    }
    a.open:hover { background: #1d4ed8; }
    a.open:active { transform: translateY(1px); }
    .meta { color: #64748b; font-size: 0.85em; margin-top: 10px; }
"""


def render_row(tool: str, prompt: str, flags: str) -> str:
    badges = []
    if "r" in flags:
        badges.append(
            '<span class="badge r" title="risky — confirmation gate">🔒</span>'
        )
    if "p" in flags:
        badges.append(
            '<span class="badge p" title="macOS permission required on first use">🔑</span>'
        )
    if "f" in flags:
        badges.append(
            '<span class="badge f" title="needs a target file — adjust the path">📎</span>'
        )
    badges_html = f'<span class="badges">{"".join(badges)}</span>' if badges else ""
    href = f"{UI_URL}/?prompt={quote(prompt, safe='')}"
    return (
        '<div class="row">'
        f'<div class="tool">{html_lib.escape(tool)}{badges_html}</div>'
        f'<div class="prompt">{html_lib.escape(prompt)}</div>'
        f'<a class="open" href="{href}" target="_blank" rel="noopener">Open →</a>'
        "</div>"
    )


def render_group(name: str, emoji: str, items: list[tuple[str, str, str]]) -> str:
    rows = "\n      ".join(render_row(t, p, f) for t, p, f in items)
    return (
        '<section class="group">'
        f"<h2>{emoji} {html_lib.escape(name)}</h2>"
        f"{rows}"
        "</section>"
    )


def render(groups) -> str:
    total = sum(len(items) for _, _, items in groups)
    sections = "\n    ".join(render_group(n, e, items) for n, e, items in groups)
    legend = (
        '<div class="legend">'
        '<span class="badge r">🔒</span> risky — confirmation gate &nbsp; '
        '<span class="badge p">🔑</span> macOS permission on first use &nbsp; '
        '<span class="badge f">📎</span> needs a target file (edit the path)'
        "</div>"
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LocalLLM smoke test ({total} tools)</title>
    <style>
{STYLE}    </style>
  </head>
  <body>
    <div class="wrap">
      <header>
        <h1>🧪 LocalLLM smoke test — {total} tools</h1>
        <div class="lede">
          Each link opens <code>{UI_URL}</code> with the prompt pre-filled, ready
          to hit send. Make sure you're in <strong>agent mode</strong>.
        </div>
        {legend}
        <div class="meta">
          Generated by <code>scripts/build_smoke_test.py</code>. Re-run to refresh.
        </div>
      </header>
      {sections}
    </div>
  </body>
</html>
"""


def main() -> int:
    out = Path(__file__).resolve().parent.parent / "docs" / "smoke-test.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(GROUPS), encoding="utf-8")
    total = sum(len(items) for _, _, items in GROUPS)
    print(f"wrote {out} ({total} tools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
