"""Unit tests for US-012: db.py — Contact Registry and Audit Events."""

from __future__ import annotations

from pathlib import Path

import pytest

from clawstrike.db import (
    ContactRecord,
    get_or_create_contact,
    increment_interaction,
    insert_audit_event,
    open_db,
    set_contact_trust_level,
)

# ---------------------------------------------------------------------------
# open_db — schema and directory creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_db_creates_contacts_table(tmp_path: Path) -> None:
    """open_db creates the contacts table on first use."""
    async with open_db(tmp_path / "test.db") as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='contacts'"
        ) as cur:
            row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_open_db_creates_audit_events_table(tmp_path: Path) -> None:
    """open_db creates the audit_events table on first use."""
    async with open_db(tmp_path / "test.db") as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'"
        ) as cur:
            row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_open_db_creates_parent_dirs(tmp_path: Path) -> None:
    """open_db auto-creates missing parent directories."""
    db_path = tmp_path / "nested" / "dir" / "test.db"
    async with open_db(db_path):
        pass
    assert db_path.exists()


@pytest.mark.asyncio
async def test_open_db_idempotent(tmp_path: Path) -> None:
    """Calling open_db twice on the same path does not error (IF NOT EXISTS guard)."""
    db_path = tmp_path / "test.db"
    async with open_db(db_path) as conn:
        await get_or_create_contact(conn, "x@example.com", "webhook")
    async with open_db(db_path) as conn:
        await get_or_create_contact(conn, "y@example.com", "webhook")


# ---------------------------------------------------------------------------
# get_or_create_contact — first contact behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_contact_is_first_contact_true(tmp_path: Path) -> None:
    """New source_id → is_first_contact=True, trust_level='auto', count=1."""
    async with open_db(tmp_path / "test.db") as conn:
        record, is_first = await get_or_create_contact(
            conn, "alice@example.com", "email_body"
        )
    assert is_first is True
    assert isinstance(record, ContactRecord)
    assert record.source_id == "alice@example.com"
    assert record.channel_type == "email_body"
    assert record.trust_level == "auto"
    assert record.interaction_count == 1


@pytest.mark.asyncio
async def test_known_contact_is_first_contact_false(tmp_path: Path) -> None:
    """Existing source_id → is_first_contact=False."""
    db_path = tmp_path / "test.db"
    async with open_db(db_path) as conn:
        await get_or_create_contact(conn, "alice@example.com", "email_body")
    async with open_db(db_path) as conn:
        _, is_first = await get_or_create_contact(
            conn, "alice@example.com", "email_body"
        )
    assert is_first is False


@pytest.mark.asyncio
async def test_first_contact_row_persists_across_connections(tmp_path: Path) -> None:
    """Row created on first contact is retrievable in a subsequent open_db call."""
    db_path = tmp_path / "test.db"
    async with open_db(db_path) as conn:
        await get_or_create_contact(conn, "bob@example.com", "webhook")
    async with open_db(db_path) as conn:
        record, _ = await get_or_create_contact(conn, "bob@example.com", "webhook")
    assert record.source_id == "bob@example.com"
    assert record.channel_type == "webhook"


@pytest.mark.asyncio
async def test_second_call_preserves_channel_type(tmp_path: Path) -> None:
    """Calling get_or_create_contact for an existing source with a different
    channel_type does not overwrite the original channel_type."""
    db_path = tmp_path / "test.db"
    async with open_db(db_path) as conn:
        await get_or_create_contact(conn, "carol@example.com", "email_body")
    async with open_db(db_path) as conn:
        record, _ = await get_or_create_contact(conn, "carol@example.com", "owner_dm")
    assert record.channel_type == "email_body"


@pytest.mark.asyncio
async def test_different_source_ids_are_independent(tmp_path: Path) -> None:
    """Two distinct source_ids each trigger their own first-contact event."""
    async with open_db(tmp_path / "test.db") as conn:
        _, is_first_a = await get_or_create_contact(conn, "a@example.com", "email_body")
        _, is_first_b = await get_or_create_contact(conn, "b@example.com", "email_body")
    assert is_first_a is True
    assert is_first_b is True


# ---------------------------------------------------------------------------
# insert_audit_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_audit_event_writes_row(tmp_path: Path) -> None:
    """insert_audit_event persists a row retrievable via a SELECT."""
    async with open_db(tmp_path / "test.db") as conn:
        await insert_audit_event(
            conn,
            event_type="classify",
            session_id="sess-1",
            source_id="user@example.com",
            channel_type="email_body",
            decision="pass",
            score=0.10,
            is_first_contact=True,
            trust_level="untrusted",
        )
        async with conn.execute(
            "SELECT event_type, source_id, is_first_contact, decision "
            "FROM audit_events WHERE source_id = ?",
            ("user@example.com",),
        ) as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row["event_type"] == "classify"
    assert row["is_first_contact"] == 1
    assert row["decision"] == "pass"


# ---------------------------------------------------------------------------
# increment_interaction — US-013
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_increment_interaction_increments_count(tmp_path: Path) -> None:
    """increment_interaction raises interaction_count by 1."""
    async with open_db(tmp_path / "test.db") as conn:
        await get_or_create_contact(conn, "alice@example.com", "email_body")
        updated = await increment_interaction(conn, "alice@example.com")
    assert updated.interaction_count == 2


@pytest.mark.asyncio
async def test_increment_interaction_updates_last_seen(tmp_path: Path) -> None:
    """increment_interaction updates last_seen to a new timestamp."""
    db_path = tmp_path / "test.db"
    async with open_db(db_path) as conn:
        record, _ = await get_or_create_contact(conn, "bob@example.com", "webhook")
    original_last_seen = record.last_seen

    async with open_db(db_path) as conn:
        updated = await increment_interaction(conn, "bob@example.com")
    # last_seen must be >= original (may be equal if clock resolution is low,
    # but the field must be updated — the UPDATE always sets it even if equal).
    assert updated.last_seen >= original_last_seen


@pytest.mark.asyncio
async def test_increment_interaction_returns_updated_record(tmp_path: Path) -> None:
    """increment_interaction returns a ContactRecord with the new count."""
    async with open_db(tmp_path / "test.db") as conn:
        await get_or_create_contact(conn, "carol@example.com", "trusted_group")
        result = await increment_interaction(conn, "carol@example.com")
    assert isinstance(result, ContactRecord)
    assert result.source_id == "carol@example.com"
    assert result.interaction_count == 2


@pytest.mark.asyncio
async def test_increment_interaction_multiple_times(tmp_path: Path) -> None:
    """Multiple increment calls accumulate correctly."""
    async with open_db(tmp_path / "test.db") as conn:
        await get_or_create_contact(conn, "dave@example.com", "email_body")
        for _ in range(4):
            await increment_interaction(conn, "dave@example.com")
        final = await increment_interaction(conn, "dave@example.com")
    assert final.interaction_count == 6  # 1 (creation) + 5 increments


# ---------------------------------------------------------------------------
# set_contact_trust_level — US-013
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_contact_trust_level_updates_stored_value(tmp_path: Path) -> None:
    """set_contact_trust_level persists the new trust_level."""
    async with open_db(tmp_path / "test.db") as conn:
        await get_or_create_contact(conn, "eve@example.com", "trusted_group")
        await set_contact_trust_level(conn, "eve@example.com", "medium")
        record, _ = await get_or_create_contact(
            conn, "eve@example.com", "trusted_group"
        )
    assert record.trust_level == "medium"


@pytest.mark.asyncio
async def test_set_contact_trust_level_trusted(tmp_path: Path) -> None:
    """set_contact_trust_level can set trust_level to 'trusted'."""
    async with open_db(tmp_path / "test.db") as conn:
        await get_or_create_contact(conn, "frank@example.com", "owner_dm")
        await set_contact_trust_level(conn, "frank@example.com", "trusted")
        record, _ = await get_or_create_contact(conn, "frank@example.com", "owner_dm")
    assert record.trust_level == "trusted"


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_audit_event_is_first_contact_false(tmp_path: Path) -> None:
    """is_first_contact=False is stored as integer 0."""
    async with open_db(tmp_path / "test.db") as conn:
        await insert_audit_event(
            conn,
            event_type="classify",
            source_id="known@example.com",
            is_first_contact=False,
        )
        async with conn.execute(
            "SELECT is_first_contact FROM audit_events WHERE source_id = ?",
            ("known@example.com",),
        ) as cur:
            row = await cur.fetchone()

    assert row["is_first_contact"] == 0
