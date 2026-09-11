"""Data model for Karne.

These dataclasses mirror the tables defined in docs/PLAN.md section 5. They are
plain data containers with no database logic; all persistence lives in
``karne.storage``. Timestamps are timezone-aware :class:`datetime` values (UTC);
the storage layer serialises them to ISO-8601 strings.

Design notes tied to the immutable rules (see CLAUDE.md):

- ``ScanResult.payload`` is the RAW, uninterpreted collector output. It is stored
  verbatim as JSON and is never overwritten (rule 1, rule 5).
- ``DnsRecord.valid`` records *syntactic* validity — a factual observation of
  whether a record parses per its RFC grammar. It is NOT a score or a quality
  judgement (rule 1). Scoring happens in a separate layer from ``scores`` /
  ``findings``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Controlled vocabularies (documentation aids; not enforced by the schema).
# ---------------------------------------------------------------------------

# scans.status lifecycle values.
STATUS_RUNNING = "running"  # scan row created, collectors not finished yet
STATUS_OK = "ok"  # every collector succeeded
STATUS_PARTIAL = "partial"  # at least one collector failed, others succeeded
STATUS_ERROR = "error"  # the scan as a whole failed

# scores.dimension values (see PLAN.md section 3).
DIMENSION_EMAIL = "email"  # A — email & domain identity (Sprint 0)
DIMENSION_TRANSPORT = "transport"  # B — transport & server security
DIMENSION_PRIVACY = "privacy"  # C — privacy & tracking
DIMENSION_TECH = "tech"  # D — technology & visible surface

# scans.consent_state / cookies.consent_state values (dimension C, Sprint 4).
CONSENT_NONE = "none"  # untouched — banner not interacted with
CONSENT_REJECTED = "rejected"
CONSENT_ACCEPTED = "accepted"


@dataclass
class Domain:
    """A domain we measure. One row per domain (``domain`` is unique)."""

    domain: str
    source: str | None = None  # where the domain came from (e.g. "tranco", "manual")
    sector: str | None = None  # e.g. "bank", "university", "public_body"
    is_public_body: bool | None = None
    added_at: datetime | None = None  # set by storage at insert time if None
    id: int | None = None


@dataclass
class Scan:
    """One measurement run of one domain. Created at start, finished at end."""

    domain_id: int
    scanner_version: str
    status: str = STATUS_RUNNING
    started_at: datetime | None = None  # set by storage at insert time if None
    finished_at: datetime | None = None
    config_hash: str | None = None  # hash of the scan config used (reproducibility)
    consent_state: str | None = None  # dimension C only; None for dimension A
    error: str | None = None  # failure detail when status is partial/error
    run_label: str | None = None  # batch round label, e.g. "2026-11"; None for ad-hoc scans
    id: int | None = None


@dataclass
class ScanResult:
    """Raw, untouchable output of one collector for one scan (rule 1, rule 5).

    ``payload`` holds the collector's dict; storage serialises it to the
    ``payload_json`` column verbatim and never overwrites it.
    """

    scan_id: int
    collector: str  # e.g. "dns_email"
    payload: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass
class DnsRecord:
    """A flattened, queryable projection of one observed DNS fact.

    The authoritative raw data is ``ScanResult.payload``; this table is a
    convenience index over it. ``valid`` is a syntactic-validity OBSERVATION,
    not a score (see module docstring).
    """

    scan_id: int
    rtype: str  # SPF, DMARC, DKIM, MX, DS, CAA, TLSA, MTA-STS, TLS-RPT, ...
    value: str | None = None
    selector: str | None = None  # DKIM selector; None otherwise
    valid: bool | None = None  # syntactic validity observation (not a score)
    notes: str | None = None  # e.g. the query result state: nxdomain/timeout/servfail
    id: int | None = None


@dataclass
class Score:
    """A derived score for one dimension of one scan (scoring layer, Sprint 3+).

    Re-derivable from raw data; records which ruleset version produced it (K-03).
    """

    scan_id: int
    dimension: str  # DIMENSION_* above
    ruleset_version: str
    raw_score: float | None = None
    grade: str | None = None  # letter grade
    id: int | None = None


@dataclass
class Finding:
    """A derived, coded finding for one scan (scoring layer, Sprint 3+).

    ``code`` comes from a fixed list (e.g. EMAIL_NO_DMARC). Human-readable text
    and fix hints live in translation files keyed by ``code`` / ``fix_hint_key``,
    not here (PLAN.md section 5).
    """

    scan_id: int
    code: str
    severity: str | None = None
    evidence: dict[str, Any] | None = None  # stored as evidence_json
    fix_hint_key: str | None = None
    id: int | None = None
