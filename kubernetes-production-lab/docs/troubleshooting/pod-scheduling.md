# Exercise: PostgreSQL Pod cannot be scheduled

## Introduce the failure

Change the PostgreSQL affinity value from `postgres` to `postgres-broken`, then apply the overlay.

```bash
kubectl -n production-lab patch deployment postgres --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/affinity/nodeAffinity/requiredDuringSchedulingIgnoredDuringExecution/nodeSelectorTerms/0/matchExpressions/0/values/0","value":"postgres-broken"}]'
```

## Investigate

```bash
kubectl -n production-lab get pods -o wide
kubectl -n production-lab describe pod -l app.kubernetes.io/name=postgres
kubectl get nodes --show-labels
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
kubectl -n production-lab get events --sort-by=.lastTimestamp
```

Expected evidence: `0/N nodes are available` and a node-affinity mismatch. The database node label is `workload=postgres`.

## Fix and verify

```bash
kubectl -n production-lab patch deployment postgres --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/affinity/nodeAffinity/requiredDuringSchedulingIgnoredDuringExecution/nodeSelectorTerms/0/matchExpressions/0/values/0","value":"postgres"}]'
kubectl -n production-lab rollout status deployment/postgres
```

Root cause: the required node affinity named a label value that no node had. The toleration alone permits a Pod onto a tainted node; it does not select that node.

