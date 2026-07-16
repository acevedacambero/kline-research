from kline.data.identity_audit import IDENTITY_AUDIT_VERSION, SecurityIdentityAudit
from kline.data.pipeline import DatasetPipeline


def test_identity_audit_finds_and_removes_only_invalid_quality_events(tmp_path):
    pipeline = DatasetPipeline(tmp_path)
    pipeline.initialize_catalog()
    pipeline.record_quality_event("stock:sh:301377", "download-failed", "error", "bad")
    pipeline.record_quality_event("stock:sz:000001", "download-failed", "error", "valid")
    audit = SecurityIdentityAudit(pipeline)

    plan = audit.scan()

    assert plan.version == IDENTITY_AUDIT_VERSION
    assert plan.invalid_event_keys == ("stock:sh:301377",)
    assert plan.invalid_manifest_keys == ()
    result = audit.purge_invalid_events(plan)
    assert result["deletedEvents"] == 1
    assert [event["dataset_key"] for event in pipeline.quality_events()] == ["stock:sz:000001"]


def test_identity_audit_refuses_event_cleanup_when_invalid_manifest_exists(tmp_path):
    pipeline = DatasetPipeline(tmp_path)
    pipeline.initialize_catalog()
    with pipeline.connection() as connection:
        connection.execute(
            """insert into dataset_manifest(
                dataset_key, content_hash, dataset_version, derived_path
            ) values ('stock:sz:601100', 'hash', 'v1', 'missing.parquet')"""
        )
    audit = SecurityIdentityAudit(pipeline)
    plan = audit.scan()

    assert plan.invalid_manifest_keys == ("stock:sz:601100",)
    try:
        audit.purge_invalid_events(plan)
    except ValueError as exc:
        assert "manual migration" in str(exc)
    else:
        raise AssertionError("cleanup should be blocked")
