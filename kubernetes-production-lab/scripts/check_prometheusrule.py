"""Check that the PrometheusRule manifest and the plain rules file agree.

Usage: python scripts/check_prometheusrule.py

observability/prometheus/alerts.yml is the source of truth (validated and unit
tested with promtool); manifests/monitoring/prometheusrule.yaml must carry the
same rule groups so the in-cluster alerts never drift from the tested ones.
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RULES_FILE = ROOT / "observability/prometheus/alerts.yml"
MANIFEST = ROOT / "manifests/monitoring/prometheusrule.yaml"
REQUIRED_ALERTS = {"BackendDown", "HighErrorRate", "HighLatency"}


def main() -> int:
    rules = yaml.safe_load(RULES_FILE.read_text())
    manifest = yaml.safe_load(MANIFEST.read_text())

    if manifest.get("kind") != "PrometheusRule":
        print(f"FAIL: {MANIFEST.name} is not a PrometheusRule")
        return 1
    if manifest["spec"]["groups"] != rules["groups"]:
        print(f"FAIL: {MANIFEST.name} spec.groups differ from {RULES_FILE.name}")
        return 1

    alerts = {r["alert"] for g in rules["groups"] for r in g["rules"] if "alert" in r}
    missing = REQUIRED_ALERTS - alerts
    if missing:
        print(f"FAIL: missing alerts: {', '.join(sorted(missing))}")
        return 1

    print(f"OK: PrometheusRule matches {RULES_FILE.name} ({', '.join(sorted(alerts))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
