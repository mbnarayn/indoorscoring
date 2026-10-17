from typing import Any

from app.services.engine import MatchError


# Match settings changes survive an undo; only play is rolled back.
PRESERVED_TYPES = frozenset({"set_overs", "set_pairing_overs"})


def is_ball(event: dict[str, Any]) -> bool:
    return event.get("type") == "ball"


def trailing_retirements(events: list[dict[str, Any]]) -> int:
    count = 0
    for event in reversed(events):
        if event.get("type") != "retire":
            break
        count += 1
    return count


def cancel_retirements(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove retirements recorded since the last action, putting those batsmen back at the crease."""
    count = trailing_retirements(events)
    if not count:
        raise MatchError("There is no retirement to cancel")
    return events[:-count]


def undo_last_ball(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the event list with the last delivery removed.

    Any selections made after that delivery (new batsman, next bowler, next innings) are removed too,
    so replaying the remaining events restores every statistic to exactly its pre-delivery value.
    If no delivery has been bowled yet, the most recent setup event is removed instead.
    """
    for idx in range(len(events) - 1, -1, -1):
        if is_ball(events[idx]):
            return events[:idx] + [e for e in events[idx + 1 :] if e.get("type") in PRESERVED_TYPES]
    if events:
        return events[:-1]
    raise MatchError("Nothing to undo")
