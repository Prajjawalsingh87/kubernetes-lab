"""Cross-object checks kubeconform can't do (it validates each object alone).

Usage: kubectl kustomize <dir> | python scripts/check_autoscaling.py

Fails if the backend HPA, Deployment and PodDisruptionBudget don't fit together:
  * the HPA targets an existing Deployment and scales on CPU utilization,
  * that Deployment sets a CPU request (HPA utilization is relative to it) and
    no `replicas:` (which would fight the HPA on every apply),
  * a PDB selects the backend Pods and still allows one eviction at minReplicas.
"""

import sys

import yaml


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def main() -> None:
    docs = [d for d in yaml.safe_load_all(sys.stdin) if d]
    by_kind: dict[str, list[dict]] = {}
    for doc in docs:
        by_kind.setdefault(doc["kind"], []).append(doc)

    hpas = by_kind.get("HorizontalPodAutoscaler", [])
    if not hpas:
        fail("no HorizontalPodAutoscaler rendered")
    deployments = {d["metadata"]["name"]: d for d in by_kind.get("Deployment", [])}
    pdbs = by_kind.get("PodDisruptionBudget", [])

    for hpa in hpas:
        name = hpa["metadata"]["name"]
        spec = hpa["spec"]
        target = spec["scaleTargetRef"]
        if target["kind"] != "Deployment" or target["name"] not in deployments:
            fail(f"HPA {name} targets missing {target['kind']}/{target['name']}")
        cpu_metrics = [
            m for m in spec.get("metrics", [])
            if m.get("type") == "Resource" and m["resource"]["name"] == "cpu"
        ]
        if not cpu_metrics:
            fail(f"HPA {name} has no CPU resource metric")
        min_replicas = spec.get("minReplicas", 1)
        if min_replicas > spec["maxReplicas"]:
            fail(f"HPA {name} minReplicas > maxReplicas")

        deployment = deployments[target["name"]]
        if "replicas" in deployment["spec"]:
            fail(f"Deployment {target['name']} sets replicas but is managed by HPA {name}")
        for container in deployment["spec"]["template"]["spec"]["containers"]:
            if not container.get("resources", {}).get("requests", {}).get("cpu"):
                fail(f"container {container['name']} has no CPU request (needed by HPA {name})")

        pod_labels = deployment["spec"]["template"]["metadata"]["labels"]
        matching = [
            p for p in pdbs
            if p["spec"]["selector"]["matchLabels"].items() <= pod_labels.items()
        ]
        if not matching:
            fail(f"no PodDisruptionBudget selects the Pods of {target['name']}")
        for pdb in matching:
            min_available = pdb["spec"].get("minAvailable")
            if isinstance(min_available, int) and min_available >= min_replicas:
                fail(
                    f"PDB {pdb['metadata']['name']} minAvailable={min_available} blocks "
                    f"all evictions at HPA minReplicas={min_replicas}"
                )
        print(
            f"OK: HPA {name} -> Deployment {target['name']} "
            f"({min_replicas}-{spec['maxReplicas']} replicas, CPU), "
            f"PDB {', '.join(p['metadata']['name'] for p in matching)}"
        )


if __name__ == "__main__":
    main()
