"""Command line entry point: ``python -m mivzak --role primary``."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import date, datetime, time as datetime_time, timedelta
from pathlib import Path

from . import config
from .config import CLOSING, ISRAEL_TZ, OPENING, OUTPUT_DIR, PAUSE
from .market_data import collect_market_data, fixture_snapshot
from .narration import build_data_paragraphs, order_paragraphs, when_phrase
from .render import docx_filename, email_subject, render_docx, render_email
from .sources import collect_sources, fixture_sources
from .state import already_sent, load_state, write_state

MIN_PARAGRAPHS_TO_SEND = 2


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and email the IBI morning brief.")
    parser.add_argument("--role", choices=("primary", "backup"), default="primary")
    parser.add_argument("--trading-date", help="YYYY-MM-DD; defaults to the last completed US session")
    parser.add_argument("--recipient", help="Override the recipient address")
    parser.add_argument("--dry-run", action="store_true", help="Build everything but do not send")
    parser.add_argument("--force-send", action="store_true", help="Ignore the sent marker")
    parser.add_argument("--offline", action="store_true", help="Use fixture data, no network")
    parser.add_argument("--skip-llm", action="store_true", help="Do not call Gemini")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


US_CLOSE_ISRAEL = datetime_time(23, 5)


def resolve_trading_date(raw: str | None, now: datetime) -> date:
    """The last completed US session, reckoned in Israel time only.

    Wall Street closes at 23:00 Israel time, so a run from 23:05 onward
    summarizes the same Israeli calendar date; earlier runs summarize the
    previous weekday.
    """
    if raw:
        return date.fromisoformat(raw)
    israel = now.astimezone(ISRAEL_TZ)
    trading_date = israel.date()
    if israel.time() < US_CLOSE_ISRAEL:
        trading_date -= timedelta(days=1)
    while trading_date.weekday() >= 5:
        trading_date -= timedelta(days=1)
    return trading_date


def set_github_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def append_step_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")


def narration_lines(paragraphs: list) -> list:
    lines = [OPENING, ""]
    for paragraph in paragraphs:
        lines.extend(paragraph.lines + [""])
    lines.extend([PAUSE, "", CLOSING])
    return lines


def run_self_test() -> None:
    from .hebrew_numbers import percent_phrase
    from .render import docx_body_text

    assert percent_phrase(0.5) == "במחצית האחוז"
    assert percent_phrase(5.5) == "בחמישה וחצי אחוזים"
    assert percent_phrase(7.2) == "בשבעה אחוזים ושתי עשיריות"
    assert percent_phrase(1.2) == "באחוז ושתי עשיריות"
    trading_date = date(2026, 9, 3)
    snapshot = fixture_snapshot(trading_date)
    paragraphs = build_data_paragraphs(snapshot, trading_date)
    assert len(paragraphs) >= 4, "fixture narration is too short"
    assert all("בב" not in paragraph.text for paragraph in paragraphs)
    output = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "mivzak-self-test.docx"
    render_docx([paragraph.text for paragraph in paragraphs], trading_date + timedelta(days=1), output)
    body = docx_body_text(output)
    assert body[-1] == PAUSE, "the pause line must close the body cell"
    expected_lines = [line for paragraph in paragraphs for line in paragraph.lines]
    assert body[:-1] == expected_lines, "docx lines differ from the narration"
    from docx import Document

    text = " ".join(cell.text for row in Document(str(output)).tables[0].rows for cell in row.cells)
    assert OPENING in text and CLOSING in text
    print("mivzak self-test passed")


def run(args: argparse.Namespace) -> int:
    now = datetime.now(ISRAEL_TZ)
    recipient = (args.recipient or "").strip() or config.recipient()
    trading_date = resolve_trading_date(args.trading_date, now)
    brief_date = trading_date + timedelta(days=1)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"Role: {args.role} | run time (Israel): {now.strftime('%Y-%m-%d %H:%M')} | "
        f"trading date: {trading_date} | brief date: {brief_date} | recipient: {recipient}"
    )
    set_github_output("trading_date", trading_date.isoformat())
    set_github_output("brief_date", brief_date.isoformat())

    state = load_state()
    if not args.dry_run and not args.force_send and already_sent(state, trading_date, recipient):
        print(
            f"The brief for {trading_date} was already sent by the "
            f"{state.get('workflow_role', 'other')} workflow at {state.get('sent_at')}. Skipping."
        )
        set_github_output("sent", "false")
        set_github_output("skipped_duplicate", "true")
        append_step_summary(f"### מבזק {brief_date}\n\nכבר נשלח על ידי ה-workflow {state.get('workflow_role')} ב-{state.get('sent_at')}.")
        return 0

    notes = []
    if args.offline:
        snapshot = fixture_snapshot(trading_date)
        sources = fixture_sources(trading_date)
        notes.append("מצב לא מקוון: נתוני דוגמה.")
    else:
        snapshot = collect_market_data(trading_date, now=now)
        notes.extend(snapshot.warnings)
        leader = snapshot.leader
        sources = collect_sources(
            trading_date,
            tavily_key=os.environ.get("TAVILY_API_KEY", "").strip(),
            exa_key=os.environ.get("EXA_API_KEY", "").strip(),
            leader_name=leader.name if leader else None,
        )
    print(f"Verified market quotes: {snapshot.verified_count()} | same-day sources: {len(sources)}")

    paragraphs = build_data_paragraphs(snapshot, trading_date)
    used_model = None
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if args.offline or args.skip_llm:
        notes.append("פסקאות החדשות לא נוצרו (ללא קריאה למודל).")
    elif not gemini_key:
        notes.append("לא הוגדר מפתח Gemini; המבזק כולל רק את פסקאות נתוני השוק המאומתות.")
    else:
        from .llm import generate_news_paragraphs

        leader = snapshot.leader
        news, used_model, llm_warnings = generate_news_paragraphs(
            trading_date=trading_date,
            brief_date=brief_date,
            sources=sources,
            existing=paragraphs,
            leader_name=leader.name if leader else None,
            api_key=gemini_key,
            when=when_phrase(trading_date),
        )
        notes.extend(llm_warnings)
        paragraphs = merge_paragraphs(paragraphs, news)

    paragraphs = order_paragraphs(paragraphs)
    texts = [paragraph.text for paragraph in paragraphs]
    lines = narration_lines(paragraphs)
    print("Generated narration:")
    print("\n".join(lines))
    if notes:
        print("Notes:")
        for note in notes:
            print(f"  - {note}")

    (output_dir / "narration.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = [f"### מבזק הידע של IBI – בוקר {brief_date} (יום מסחר {trading_date})", ""]
    summary.extend(lines)
    if used_model:
        summary.extend(["", f"Gemini model: `{used_model}`"])
    if notes:
        summary.extend(["", "**הערות:**"] + [f"- {note}" for note in notes])
    append_step_summary("\n".join(summary))

    if len(paragraphs) < MIN_PARAGRAPHS_TO_SEND:
        print(f"Only {len(paragraphs)} paragraph(s) could be verified; refusing to send a thin brief.")
        set_github_output("sent", "false")
        set_github_output("skipped_duplicate", "false")
        return 2

    docx_path = render_docx(texts, brief_date, output_dir / docx_filename(brief_date))
    plain_body, rich_body = render_email(trading_date, brief_date, paragraphs, notes)
    (output_dir / "email.html").write_text(rich_body, encoding="utf-8")
    print(f"DOCX generated at {docx_path}")
    set_github_output("docx_path", str(docx_path))
    set_github_output("degraded", "true" if notes else "false")

    if args.dry_run:
        print("Dry run: email not sent.")
        set_github_output("sent", "false")
        set_github_output("skipped_duplicate", "false")
        return 0

    from .mailer import required_secret, send_brief

    sender = required_secret("GMAIL_ADDRESS")
    app_password = required_secret("GMAIL_APP_PASSWORD")
    send_brief(
        sender=sender,
        app_password=app_password,
        recipient=recipient,
        subject=email_subject(brief_date),
        plain_body=plain_body,
        rich_body=rich_body,
        attachment_path=docx_path,
    )
    write_state(
        trading_date=trading_date,
        brief_date=brief_date,
        role=args.role,
        recipient=recipient,
        paragraph_texts=texts,
        now=now,
    )
    set_github_output("sent", "true")
    set_github_output("skipped_duplicate", "false")
    print(f"Brief sent to {recipient} by the {args.role} workflow.")
    return 0


def merge_paragraphs(data_paragraphs: list, news_paragraphs: list) -> list:
    """Attach the leader reason (and Hebrew name) to the leader line; keep the rest."""
    merged = list(data_paragraphs)
    for paragraph in news_paragraphs:
        if paragraph.category == "leader_reason":
            leader = next((item for item in merged if item.category == "leader"), None)
            if leader is None:
                continue
            lines = leader.lines
            if not lines:
                continue
            english_name = leader.data.get("leader_name")
            hebrew_name = paragraph.data.get("hebrew_name")
            if english_name and hebrew_name and f"מניית {english_name} " in lines[0]:
                lines[0] = lines[0].replace(
                    f"מניית {english_name} ", f"מניית {hebrew_name} ({english_name}) ", 1
                )
            lines[0] = lines[0].rstrip() + " " + " ".join(paragraph.lines)
            leader.text = "\n".join(lines)
            leader.sources.extend(paragraph.sources)
            leader.source_ids.extend(paragraph.source_ids)
            continue
        merged.append(paragraph)
    return merged


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.self_test:
        run_self_test()
        return 0
    try:
        return run(args)
    except Exception as error:  # noqa: BLE001 - surface everything in the job log
        traceback.print_exc()
        print(f"Mivzak failed: {error}")
        set_github_output("sent", "false")
        set_github_output("skipped_duplicate", "false")
        return 1


if __name__ == "__main__":
    sys.exit(main())
