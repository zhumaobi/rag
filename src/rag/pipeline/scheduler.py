from __future__ import annotations

import argparse
import json
from pathlib import Path

from clients.postgres_client import PostgresClient
from clients.s3_client import S3Client
from raglog import get_logger
from pipeline.orchestrator import IndexPipeline

log = get_logger("scheduler")


def _load_domain_terms(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _discover_tenants(s3: S3Client | None = None) -> list[str]:
    """Tenants are top-level prefixes in the raw-docs bucket."""
    s3 = s3 or S3Client()
    tenants: set[str] = set()
    paginator = s3._client.get_paginator("list_objects_v2")  # noqa: SLF001 - internal reuse
    for page in paginator.paginate(Bucket=s3._raw_bucket, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            tenants.add(cp["Prefix"].rstrip("/"))
    return sorted(tenants)


def run_scheduled(run_id: str, domain_terms_path: str | None) -> None:
    """Daily low-peak trigger: rebuild indices for every tenant that has raw docs."""
    PostgresClient().init_schema()
    domain_terms = _load_domain_terms(domain_terms_path)
    for tenant_id in _discover_tenants():
        _run_one(tenant_id, f"{run_id}_{tenant_id}", domain_terms)


def run_manual(tenant_id: str, run_id: str, domain_terms_path: str | None) -> None:
    """Manual emergency trigger for a single tenant."""
    PostgresClient().init_schema()
    _run_one(tenant_id, run_id, _load_domain_terms(domain_terms_path))


def _run_one(tenant_id: str, run_id: str, domain_terms: dict[str, str]) -> None:
    pipeline = IndexPipeline(domain_terms=domain_terms)
    try:
        result = pipeline.run(tenant_id, run_id)
        log.info("run_complete", tenant_id=tenant_id, run_id=run_id, state=result.state.value)
    except Exception as exc:
        log.error("run_error", tenant_id=tenant_id, run_id=run_id, error=str(exc))


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline index pipeline runner")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_sched = sub.add_parser("scheduled", help="rebuild all tenants (daily low-peak cron)")
    p_sched.add_argument("--run-id", required=True)
    p_sched.add_argument("--domain-terms")

    p_manual = sub.add_parser("manual", help="emergency single-tenant rebuild")
    p_manual.add_argument("--tenant-id", required=True)
    p_manual.add_argument("--run-id", required=True)
    p_manual.add_argument("--domain-terms")

    args = parser.parse_args()
    if args.mode == "scheduled":
        run_scheduled(args.run_id, args.domain_terms)
    else:
        run_manual(args.tenant_id, args.run_id, args.domain_terms)


if __name__ == "__main__":
    main()
