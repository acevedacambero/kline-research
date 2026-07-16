from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

from .pipeline import DatasetPipeline
from .security_identity import SecurityIdentityError, validate_security_identity


IDENTITY_AUDIT_VERSION = "security-identity-audit-v1"


def _invalid_stock_key(dataset_key: str) -> bool:
    parts = str(dataset_key).split(":")
    if len(parts) != 3 or parts[0] != "stock":
        return False
    try:
        validate_security_identity(parts[1], parts[2])
    except SecurityIdentityError:
        return True
    return False


@dataclass(frozen=True)
class IdentityAuditPlan:
    version: str
    plan_id: str
    data_root: str
    invalid_event_ids: tuple[str, ...]
    invalid_event_keys: tuple[str, ...]
    invalid_manifest_keys: tuple[str, ...]
    invalid_master_securities: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "IdentityAuditPlan":
        return cls(
            version=str(value["version"]),
            plan_id=str(value["plan_id"]),
            data_root=str(value["data_root"]),
            invalid_event_ids=tuple(value["invalid_event_ids"]),
            invalid_event_keys=tuple(value["invalid_event_keys"]),
            invalid_manifest_keys=tuple(value["invalid_manifest_keys"]),
            invalid_master_securities=tuple(value["invalid_master_securities"]),
        )


class SecurityIdentityAudit:
    def __init__(self, pipeline: DatasetPipeline):
        self.pipeline = pipeline

    @staticmethod
    def _plan_id(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def scan(self) -> IdentityAuditPlan:
        with self.pipeline.connection() as connection:
            events = connection.execute(
                "select event_id, dataset_key from data_quality_events order by event_id"
            ).fetchall()
            manifests = connection.execute(
                "select dataset_key from dataset_manifest order by dataset_key"
            ).fetchall()
        invalid_events = [(str(event_id), str(key)) for event_id, key in events if _invalid_stock_key(key)]
        invalid_manifest_keys = tuple(
            str(row[0]) for row in manifests if _invalid_stock_key(str(row[0]))
        )
        invalid_master = []
        for item in self.pipeline.load_security_master():
            exchange, code = str(item.get("exchange", "")), str(item.get("code", ""))
            try:
                validate_security_identity(exchange, code)
            except SecurityIdentityError:
                invalid_master.append(f"{exchange}{code}")
        payload = {
            "version": IDENTITY_AUDIT_VERSION,
            "data_root": str(self.pipeline.output_root.resolve()),
            "invalid_event_ids": [item[0] for item in invalid_events],
            "invalid_event_keys": [item[1] for item in invalid_events],
            "invalid_manifest_keys": list(invalid_manifest_keys),
            "invalid_master_securities": sorted(invalid_master),
        }
        return IdentityAuditPlan(
            plan_id=self._plan_id(payload),
            invalid_event_ids=tuple(payload["invalid_event_ids"]),
            invalid_event_keys=tuple(payload["invalid_event_keys"]),
            invalid_manifest_keys=invalid_manifest_keys,
            invalid_master_securities=tuple(payload["invalid_master_securities"]),
            version=IDENTITY_AUDIT_VERSION,
            data_root=payload["data_root"],
        )

    def purge_invalid_events(self, plan: IdentityAuditPlan) -> dict[str, Any]:
        current = self.scan()
        if plan != current:
            raise ValueError("stale or tampered identity audit plan")
        if plan.invalid_manifest_keys or plan.invalid_master_securities:
            raise ValueError("invalid cached identities require manual migration before event cleanup")
        with self.pipeline.connection() as connection:
            connection.execute("begin transaction")
            try:
                if plan.invalid_event_ids:
                    placeholders = ",".join("?" for _ in plan.invalid_event_ids)
                    connection.execute(
                        f"delete from data_quality_events where event_id in ({placeholders})",
                        list(plan.invalid_event_ids),
                    )
                connection.execute("commit")
            except Exception:
                connection.execute("rollback")
                raise
        return {
            "version": IDENTITY_AUDIT_VERSION,
            "planId": plan.plan_id,
            "status": "completed",
            "deletedEvents": len(plan.invalid_event_ids),
        }
