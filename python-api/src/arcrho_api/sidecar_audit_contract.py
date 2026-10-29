"""Canonical vocabulary, policy, and reader for persisted audit entries.

Every Arco dataset sidecar carries an ``audit_log``: one entry per durable
write, naming when it happened, which action produced it, and who ran it. The
entries are appended by the per-method output-sidecar builders in this package
(``build_dfm_output_sidecar`` and its siblings), by the engine sidecar
builder, and by the dataset writers in the app server. The project-level
``audit_log.json`` is the same kind of log at project scope.

Two kinds of writer share that log. A person saving an object records
``Insert``/``Update``; an automation that rewrote the object without anyone
opening it -- the Engine dependent-propagation walk re-publishing a method
whose precedent moved -- records ``Auto Refresh``. Telling those apart is what
lets a reader name *what* changed an object rather than only *when*, so the
action names and that classification live here once instead of being repeated
as literals at every producer and consumer.

There is one policy for every log, and it lives here so no writer can keep a
private one: every action is kept, a run of consecutive automatic entries
on one calendar day collapses to its most recent member (a propagation walk
that republishes the same output ten times is one fact, not ten, while a
refresh on a later day stays a separate record), and the log is capped at
:data:`DATASET_AUDIT_LOG_MAX_ENTRIES` records for a dataset and
:data:`PROJECT_AUDIT_LOG_MAX_ENTRIES` for a project, oldest dropped first.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


AUDIT_ACTION_INSERT = "Insert"
AUDIT_ACTION_UPDATE = "Update"
AUDIT_ACTION_AUTO_REFRESH = "Auto Refresh"

# Actions a person performs on an object they opened.
INTERACTIVE_AUDIT_ACTIONS = frozenset({AUDIT_ACTION_INSERT, AUDIT_ACTION_UPDATE})
# Actions a background process performs on an object nobody opened.
AUTOMATIC_AUDIT_ACTIONS = frozenset({AUDIT_ACTION_AUTO_REFRESH})

# The one cap per log kind. Observed logs hold a handful of records (p90 is
# three); these bound the pathological case without ever trimming real use.
DATASET_AUDIT_LOG_MAX_ENTRIES = 200
PROJECT_AUDIT_LOG_MAX_ENTRIES = 500

# The ``change_info`` a writer records when it has nothing more specific to say.
AUDIT_CHANGE_INFO_VALUES = "Values"

# A human review decision moves no number, so it names itself rather than
# taking the default above. These are the two decisions a reader can act on:
# the Project Instance table's Mark For Review and Set Reviewed.
AUDIT_CHANGE_INFO_MARK_FOR_REVIEW = "Marked For Review"
AUDIT_CHANGE_INFO_SET_REVIEWED = "Set Reviewed"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def default_change_info(action: Any) -> str:
    """The ``change_info`` an action carries when the writer gives none."""

    return "" if normalize_audit_action(action) == AUDIT_ACTION_INSERT else AUDIT_CHANGE_INFO_VALUES


def normalize_audit_entry(raw: Any) -> dict[str, str] | None:
    """Return one stored entry in its canonical shape, or ``None`` if unusable.

    An entry needs a date and an action; everything else defaults. Legacy
    Title Case keys are read so a log written before the vocabulary settled
    is not discarded. ``entry_id`` is kept only when the writer supplied one:
    the project log's hosted append carries it so a repeated request lands
    once, and every other entry has none.
    """

    if not isinstance(raw, Mapping):
        return None
    event_date = _clean(raw.get("event_date") or raw.get("Event Date"))
    action = normalize_audit_action(raw.get("action") or raw.get("Action"))
    if not event_date or not action:
        return None
    change_info = _clean(raw.get("change_info") or raw.get("Change Info"))
    if action == AUDIT_ACTION_INSERT:
        change_info = ""
    elif not change_info and action == AUDIT_ACTION_UPDATE:
        change_info = AUDIT_CHANGE_INFO_VALUES
    entry = {
        "event_date": event_date,
        "action": action,
        "change_info": change_info,
        "user": _clean(raw.get("user") or raw.get("User")),
    }
    entry_id = _clean(raw.get("entry_id"))
    if entry_id:
        entry["entry_id"] = entry_id
    return entry


def normalize_audit_log(
    entries: Any,
    *,
    max_entries: int = DATASET_AUDIT_LOG_MAX_ENTRIES,
) -> list[dict[str, str]]:
    """Apply the one audit policy to a stored log.

    Every usable entry is kept whatever its action; consecutive automatic
    entries on the same calendar day collapse to the most recent one; the
    newest ``max_entries`` remain.
    """

    kept: list[dict[str, str]] = []
    for raw in entries if isinstance(entries, Iterable) and not isinstance(entries, (str, bytes, Mapping)) else ():
        entry = normalize_audit_entry(raw)
        if entry is None:
            continue
        if (
            kept
            and is_automatic_audit_action(entry["action"])
            and is_automatic_audit_action(kept[-1]["action"])
            and entry["event_date"][:10] == kept[-1]["event_date"][:10]
        ):
            kept[-1] = entry
            continue
        kept.append(entry)
    if max_entries > 0 and len(kept) > max_entries:
        kept = kept[-max_entries:]
    return kept


def append_audit_entry(
    entries: Any,
    *,
    event_date: Any,
    action: Any,
    user: Any = "",
    change_info: Any = None,
    max_entries: int = DATASET_AUDIT_LOG_MAX_ENTRIES,
    entry_id: Any = None,
) -> list[dict[str, str]]:
    """Return *entries* with one more record, under the one audit policy."""

    action_name = normalize_audit_action(action)
    record = {
        "event_date": _clean(event_date),
        "action": action_name,
        "change_info": default_change_info(action_name) if change_info is None else _clean(change_info),
        "user": _clean(user),
        "entry_id": _clean(entry_id),
    }
    existing = list(entries) if isinstance(entries, Iterable) and not isinstance(entries, (str, bytes, Mapping)) else []
    return normalize_audit_log([*existing, record], max_entries=max_entries)


def normalize_audit_action(value: Any) -> str:
    """Return a stored action name in its canonical casing, or ``""``."""

    text = _clean(value)
    if not text:
        return ""
    folded = text.casefold()
    for known in (*INTERACTIVE_AUDIT_ACTIONS, *AUTOMATIC_AUDIT_ACTIONS):
        if folded == known.casefold():
            return known
    return text


def is_automatic_audit_action(value: Any) -> bool:
    """Say whether an action was produced by automation rather than a person."""

    return normalize_audit_action(value) in AUTOMATIC_AUDIT_ACTIONS


def latest_audit_entry(
    payload: Mapping[str, Any] | None,
    *,
    skip_automatic: bool = False,
) -> dict[str, str]:
    """Project the last usable ``audit_log`` entry of a sidecar payload.

    Entries are appended in write order, so the last one that names an action
    describes the write that produced the file as it stands. ``skip_automatic``
    passes over ``Auto Refresh`` entries to find the last write a person made.
    """

    entries = (payload or {}).get("audit_log")
    if not isinstance(entries, list):
        return {}
    for raw in reversed(entries):
        if not isinstance(raw, Mapping):
            continue
        action = normalize_audit_action(raw.get("action") or raw.get("Action"))
        if not action or (skip_automatic and is_automatic_audit_action(action)):
            continue
        return {
            "action": action,
            "at": _clean(raw.get("event_date") or raw.get("Event Date")),
            "user": _clean(raw.get("user") or raw.get("User")),
            "change_info": _clean(raw.get("change_info") or raw.get("Change Info")),
        }
    return {}


__all__ = [
    "AUDIT_ACTION_AUTO_REFRESH",
    "AUDIT_ACTION_INSERT",
    "AUDIT_ACTION_UPDATE",
    "AUDIT_CHANGE_INFO_MARK_FOR_REVIEW",
    "AUDIT_CHANGE_INFO_SET_REVIEWED",
    "AUDIT_CHANGE_INFO_VALUES",
    "AUTOMATIC_AUDIT_ACTIONS",
    "DATASET_AUDIT_LOG_MAX_ENTRIES",
    "INTERACTIVE_AUDIT_ACTIONS",
    "PROJECT_AUDIT_LOG_MAX_ENTRIES",
    "append_audit_entry",
    "default_change_info",
    "is_automatic_audit_action",
    "latest_audit_entry",
    "normalize_audit_action",
    "normalize_audit_entry",
    "normalize_audit_log",
    "sidecar_attribution",
]


def sidecar_attribution(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Name the write that left a sidecar in its current state.

    The audit entry is the primary source because it carries the action; the
    sidecar's own ``modified_by``/``updated_at`` fill in whatever the entry
    does not have (a payload written with ``append_audit=False`` keeps both).
    """

    record = payload if isinstance(payload, Mapping) else {}
    entry = latest_audit_entry(record)
    action = entry.get("action", "")
    return {
        "user": entry.get("user") or _clean(record.get("modified_by") or record.get("user")),
        "action": action,
        "at": entry.get("at") or _clean(record.get("updated_at")),
        "automatic": is_automatic_audit_action(action),
    }
