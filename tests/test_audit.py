"""Tests for configuration audit log."""

from gokart.config.audit import AuditLog


def test_audit_records_accept_and_reject(tmp_path) -> None:
    db = tmp_path / "sessions.sqlite"
    audit = AuditLog(db_path=db)
    audit.record(
        actor="test",
        entity_type="vehicle",
        entity_id="kart:V1",
        from_hash=None,
        to_hash="abc",
        diff_summary="created",
        validation_ok=True,
        validation_messages=[],
    )
    audit.record(
        actor="test",
        entity_type="vehicle",
        entity_id="kart:V1",
        from_hash="abc",
        to_hash=None,
        diff_summary="rejected",
        validation_ok=False,
        validation_messages=["speed too high"],
    )
    entries = audit.list_entries()
    assert len(entries) == 2
    assert entries[0].validation_ok is False
    assert entries[1].validation_ok is True
