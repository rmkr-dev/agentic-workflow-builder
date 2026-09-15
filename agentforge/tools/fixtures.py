"""Deterministic security-analysis tools that look like real APIs.

These run offline from a built-in CVE catalog so CI and local demos need no
API keys. Set ``AGENTFORGE_NVD_HTTP=1`` to attempt a live NVD REST lookup
(falling back to the catalog on any network/HTTP error, with ``source`` set
honestly). Optional extra records: ``AGENTFORGE_NVD_FIXTURE`` path to JSON.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)

# Well-known incidents used by examples/12-security-incident (offline catalog).
NVD_CATALOG: dict[str, dict[str, Any]] = {
    "CVE-2024-3094": {
        "cve_id": "CVE-2024-3094",
        "title": "XZ Utils malicious backdoor in liblzma",
        "severity": "CRITICAL",
        "cvss": 10.0,
        "published": "2024-03-29",
        "cwe": ["CWE-506"],
        "affected_products": ["xz-utils", "liblzma", "systemd (indirect)"],
        "description": (
            "Malicious code was inserted into xz-utils (liblzma) affecting versions "
            "5.6.0 and 5.6.1. The backdoor can intercept sshd authentication via "
            "systemd/journald linkage on some Linux distributions."
        ),
        "references": [
            "https://nvd.nist.gov/vuln/detail/CVE-2024-3094",
            "https://www.openwall.com/lists/oss-security/2024/03/29/4",
        ],
        "exploitability": "network_preauth_sshd_when_linked",
        "patch": "Downgrade or upgrade to a non-backdoored xz-utils release; rebuild sshd.",
    },
    "CVE-2024-3400": {
        "cve_id": "CVE-2024-3400",
        "title": "Palo Alto PAN-OS GlobalProtect command injection",
        "severity": "CRITICAL",
        "cvss": 10.0,
        "published": "2024-04-12",
        "cwe": ["CWE-77"],
        "affected_products": ["PAN-OS GlobalProtect gateway"],
        "description": (
            "Command injection in the GlobalProtect feature of Palo Alto Networks PAN-OS "
            "software allows unauthenticated attackers to execute code on the firewall."
        ),
        "references": ["https://nvd.nist.gov/vuln/detail/CVE-2024-3400"],
        "exploitability": "unauthenticated_network",
        "patch": "Apply PAN-OS hotfix; disable GlobalProtect if unpatched.",
    },
    "CVE-2021-44228": {
        "cve_id": "CVE-2021-44228",
        "title": "Apache Log4j2 JNDI LDAP injection (Log4Shell)",
        "severity": "CRITICAL",
        "cvss": 10.0,
        "published": "2021-12-10",
        "cwe": ["CWE-917", "CWE-502"],
        "affected_products": ["Apache Log4j 2.0-beta9 through 2.14.1"],
        "description": (
            "JNDI injection via crafted log messages can lead to remote code execution."
        ),
        "references": ["https://nvd.nist.gov/vuln/detail/CVE-2021-44228"],
        "exploitability": "unauthenticated_when_logs_attacker_controlled",
        "patch": "Upgrade Log4j to 2.17.1+ or apply vendor mitigations.",
    },
}


def extract_cve_id(state: dict[str, Any]) -> str:
    """Pull a CVE id from structured payload, common keys, or free text."""
    for key in ("cve_id", "cve", "id"):
        raw = state.get(key)
        if raw:
            match = CVE_RE.search(str(raw))
            if match:
                return match.group(0).upper()
    payload = state.get("payload") if isinstance(state.get("payload"), dict) else {}
    for key in ("cve_id", "cve", "id"):
        raw = payload.get(key)
        if raw:
            match = CVE_RE.search(str(raw))
            if match:
                return match.group(0).upper()
    blob = " ".join(
        str(state.get(k, "")) for k in ("input", "query", "output") if state.get(k)
    )
    match = CVE_RE.search(blob)
    return match.group(0).upper() if match else ""


def _load_extra_catalog() -> dict[str, dict[str, Any]]:
    extra: dict[str, dict[str, Any]] = {}
    env_path = os.environ.get("AGENTFORGE_NVD_FIXTURE", "").strip()
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path("nvd_catalog.json"))
    here = Path(__file__).resolve()
    repo = here.parents[2] if len(here.parents) >= 2 else Path.cwd()
    candidates.append(repo / "examples" / "12-security-incident" / "nvd_catalog.json")
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                records = data.get("cves", data)
                if isinstance(records, dict):
                    for key, value in records.items():
                        if isinstance(value, dict):
                            extra[str(key).upper()] = value
            break
    return extra


def load_nvd_catalog() -> dict[str, dict[str, Any]]:
    catalog = {k.upper(): dict(v) for k, v in NVD_CATALOG.items()}
    catalog.update(_load_extra_catalog())
    return catalog


def _unknown_record(cve_id: str) -> dict[str, Any]:
    return {
        "cve_id": cve_id or "UNKNOWN",
        "title": "Not in local NVD catalog",
        "severity": "UNKNOWN",
        "cvss": None,
        "published": None,
        "cwe": [],
        "affected_products": [],
        "description": (
            f"No fixture record for {cve_id or 'missing CVE id'}. "
            "Add it to AGENTFORGE_NVD_FIXTURE or enable AGENTFORGE_NVD_HTTP=1."
        ),
        "references": [],
        "exploitability": "unknown",
        "patch": "Triage manually.",
        "in_catalog": False,
    }


def _http_nvd_lookup(cve_id: str) -> dict[str, Any] | None:
    """Optional live NVD API. Returns None on any failure (caller uses catalog)."""
    flag = os.environ.get("AGENTFORGE_NVD_HTTP", "").strip().lower()
    if flag not in {"1", "true", "yes", "on"}:
        return None
    if not cve_id:
        return None
    try:
        import httpx
    except ImportError:
        return None
    url = "https://services.nvd.nist.gov/rest/json/cves/2.0"
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                url,
                params={"cveId": cve_id},
                headers={"User-Agent": "agentforge-nvd-lookup/0.1"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None
    items = data.get("vulnerabilities") if isinstance(data, dict) else None
    if not items:
        return None
    cve = (items[0] or {}).get("cve") or {}
    metrics = cve.get("metrics") or {}
    cvss = None
    severity = "UNKNOWN"
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        series = metrics.get(key) or []
        if series:
            cvss_data = (series[0] or {}).get("cvssData") or {}
            cvss = cvss_data.get("baseScore")
            severity = (
                (series[0] or {}).get("baseSeverity")
                or cvss_data.get("baseSeverity")
                or severity
            )
            break
    descs = cve.get("descriptions") or []
    description = ""
    for d in descs:
        if d.get("lang") == "en":
            description = str(d.get("value") or "")
            break
    if not description and descs:
        description = str(descs[0].get("value") or "")
    return {
        "cve_id": cve_id,
        "title": (cve.get("id") or cve_id) + " (NVD live)",
        "severity": str(severity).upper(),
        "cvss": cvss,
        "published": cve.get("published"),
        "cwe": [
            w.get("value")
            for w in ((cve.get("weaknesses") or [{}])[0].get("description") or [])
            if w.get("value")
        ],
        "affected_products": [],
        "description": description,
        "references": [
            r.get("url") for r in (cve.get("references") or [])[:5] if r.get("url")
        ],
        "exploitability": "see_nvd",
        "patch": "See NVD / vendor advisory.",
        "in_catalog": False,
        "source": "nvd_http",
        "raw_keys": list(cve.keys())[:12],
    }


def nvd_lookup(state: dict[str, Any]) -> dict[str, Any]:
    """NVD-like vulnerability lookup (fixture catalog, optional live HTTP)."""
    cve_id = extract_cve_id(state)
    live = _http_nvd_lookup(cve_id)
    if live:
        return live
    catalog = load_nvd_catalog()
    record = catalog.get(cve_id) or _unknown_record(cve_id)
    out = dict(record)
    out["source"] = "fixture_catalog"
    out["in_catalog"] = cve_id in catalog
    return out


def cloud_exposure(state: dict[str, Any]) -> dict[str, Any]:
    """Analyze optional cloud inventory from structured input for blast radius."""
    payload = state.get("payload") if isinstance(state.get("payload"), dict) else {}
    cloud = state.get("cloud") if isinstance(state.get("cloud"), dict) else payload.get("cloud")
    if not isinstance(cloud, dict):
        cloud = {}
    assets = list(cloud.get("assets") or [])
    public = [a for a in assets if isinstance(a, dict) and a.get("public")]
    ssh_like = [
        a
        for a in assets
        if isinstance(a, dict)
        and str(a.get("type", "")).lower() in {"ec2", "instance", "vm", "compute"}
    ]
    severity = "low"
    if public and ssh_like:
        severity = "critical"
    elif public or ssh_like:
        severity = "high"
    elif assets:
        severity = "medium"
    cve = nvd_lookup(state)
    notes: list[str] = []
    if cve.get("cve_id") == "CVE-2024-3094" and ssh_like:
        notes.append("XZ backdoor is relevant to sshd/liblzma on Linux compute.")
    if public:
        notes.append(f"{len(public)} internet-exposed asset(s) increase exploitability.")
    if not assets:
        notes.append("No cloud inventory provided; exposure is unverified.")
    return {
        "provider": cloud.get("provider") or "unknown",
        "account_id": cloud.get("account_id"),
        "region": cloud.get("region"),
        "asset_count": len(assets),
        "public_assets": public,
        "compute_assets": ssh_like,
        "exposure_severity": severity,
        "notes": notes,
        "source": "fixture_inventory",
    }


def iam_impact(state: dict[str, Any]) -> dict[str, Any]:
    """Identity / IAM blast-radius from optional identity context."""
    payload = state.get("payload") if isinstance(state.get("payload"), dict) else {}
    identity = (
        state.get("identity")
        if isinstance(state.get("identity"), dict)
        else payload.get("identity")
    )
    if not isinstance(identity, dict):
        identity = {}
    roles = [str(r) for r in (identity.get("roles") or [])]
    overprivileged = bool(identity.get("overprivileged"))
    adminish = any("admin" in r.lower() or r.lower() == "root" for r in roles)
    severity = "low"
    if overprivileged or adminish:
        severity = "high"
    if overprivileged and adminish:
        severity = "critical"
    if not roles and not identity:
        severity = "unknown"
    return {
        "roles": roles,
        "overprivileged": overprivileged,
        "admin_equivalent": adminish,
        "impact_severity": severity,
        "notes": [
            "Admin-equivalent roles can turn a host compromise into account takeover.",
            "Require human approval before recommending IAM changes.",
        ],
        "source": "fixture_identity",
    }


def assemble_cve_report(state: dict[str, Any]) -> dict[str, Any]:
    """Join specialist artifacts into a structured risk report."""
    artifacts = dict(state.get("artifacts") or {})
    nvd = artifacts.get("nvd_lookup")
    if not isinstance(nvd, dict):
        nvd = nvd_lookup(state)
    cloud = artifacts.get("cloud_exposure")
    if not isinstance(cloud, dict):
        cloud = cloud_exposure(state)
    iam = artifacts.get("iam_impact")
    if not isinstance(iam, dict):
        iam = iam_impact(state)
    approved = bool(state.get("approved"))
    pending = bool(state.get("pending_approval"))
    eval_passed = state.get("eval_passed")
    scores = state.get("scores") if isinstance(state.get("scores"), dict) else {}
    cve_id = nvd.get("cve_id") or extract_cve_id(state) or "UNKNOWN"
    severity = str(nvd.get("severity") or "UNKNOWN").upper()

    remediation: list[dict[str, Any]] = []
    if approved:
        patch = nvd.get("patch") or "Apply vendor guidance."
        remediation = [
            {
                "id": "patch-affected-software",
                "priority": "P0",
                "action": patch,
            },
            {
                "id": "restrict-exposure",
                "priority": "P0" if cloud.get("exposure_severity") in {"high", "critical"} else "P1",
                "action": "Remove public ingress / isolate affected compute until patched.",
            },
            {
                "id": "review-iam",
                "priority": "P1" if iam.get("impact_severity") in {"high", "critical"} else "P2",
                "action": "Review admin-equivalent roles on affected accounts; rotate credentials.",
            },
        ]
        status = "approved"
    elif pending:
        status = "pending_human_approval"
    else:
        status = "draft_pending_approval"

    report = {
        "cve_id": cve_id,
        "title": nvd.get("title"),
        "severity": severity,
        "cvss": nvd.get("cvss"),
        "summary": nvd.get("description"),
        "specialists": {
            "vulnerability": {"source": nvd.get("source"), "in_catalog": nvd.get("in_catalog", True)},
            "cloud": {"exposure_severity": cloud.get("exposure_severity"), "asset_count": cloud.get("asset_count")},
            "iam": {"impact_severity": iam.get("impact_severity"), "admin_equivalent": iam.get("admin_equivalent")},
        },
        "cloud_exposure": cloud,
        "iam_impact": iam,
        "quality": {
            "eval_passed": bool(eval_passed) if eval_passed is not None else None,
            "scores": {k: v for k, v in scores.items() if isinstance(v, (int, float))},
        },
        "approval": {
            "required": True,
            "approved": approved,
            "status": "approved" if approved else status,
        },
        "remediation_actions": remediation,
        "status": "approved" if approved else status,
    }
    return report


def ticket_note(state: dict[str, Any]) -> dict[str, Any]:
    """Deterministic stand-in used when MCP echo is granted as a ticket note."""
    cve_id = extract_cve_id(state)
    return {
        "ticket": f"SEC-{cve_id or 'UNKNOWN'}",
        "note": f"Security incident analysis started for {cve_id or 'unknown CVE'}.",
        "source": "deterministic_ticket_note",
    }
