from datetime import UTC, timedelta

from app.modules.calendar.application.calendar_subscription import CalendarEvent


def render_icalendar(*, events: list[CalendarEvent], duration_minutes: int) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TalentFlow//Interview Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for event in events:
        start = event.scheduled_at.astimezone(UTC)
        end = start + timedelta(minutes=duration_minutes)
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{event.id}@talentflow",
                f"DTSTAMP:{_format(start)}",
                f"DTSTART:{_format(start)}",
                f"DTEND:{_format(end)}",
                "SUMMARY:TalentFlow interview",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _format(value) -> str:
    return value.strftime("%Y%m%dT%H%M%SZ")
