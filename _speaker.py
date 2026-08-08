"""
Resolve WHO is speaking from the authenticated session — never from bot-supplied input.

A memory tool must not let the model (or whoever is talking to it) claim to be a different
person; otherwise one speaker could read or poison another's memories. So the speaker identity
is resolved server-side from the session the gatekeeper minted, via GET /session-info. The bot
never gets to say who it's talking to.
"""

import structlog

log = structlog.get_logger()


async def resolve_speaker(tool) -> dict:
    """Return {speaker_id, speaker_label, source_interface, session_id} for the current session.

    Falls back to a null speaker (owner/session scope still work) if the session can't be
    resolved — we degrade to "unknown speaker" rather than trust bot-provided identity.
    """
    session_id = getattr(tool, "_session_id", None)
    gk = getattr(tool, "_gatekeeper_url", None)
    out = {"speaker_id": None, "speaker_label": None, "source_interface": None, "session_id": session_id}
    if not session_id or not gk:
        return out
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{gk}/session-info", params={"session_id": session_id}, timeout=5.0)
        if resp.status_code != 200:
            return out
        info = resp.json() or {}
        source = info.get("source") or ""
        user_id = info.get("user_id") or ""
        if source and user_id:
            out["speaker_id"] = f"{source}:{user_id}"
            out["speaker_label"] = info.get("user_label") or user_id
            out["source_interface"] = source
    except Exception as e:
        log.warning("resolve_speaker_failed", error=str(e))
    return out
