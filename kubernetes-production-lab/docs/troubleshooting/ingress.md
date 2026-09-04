# Exercise: `/api` traffic is routed to the wrong Service

## Introduce the failure

```bash
kubectl -n production-lab patch ingress application --type=json \
  -p='[{"op":"replace","path":"/spec/rules/0/http/paths/0/backend/service/name","value":"frontend"},{"op":"replace","path":"/spec/rules/0/http/paths/0/backend/service/port/number","value":80}]'
```

## Investigate

```bash
kubectl -n production-lab get ingress application
kubectl -n production-lab describe ingress application
kubectl -n kube-system logs deployment/aws-load-balancer-controller --since=10m
ALB_HOST=$(kubectl -n production-lab get ingress application -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
curl -i "http://${ALB_HOST}/api/database"
```

Expected evidence: the ALB is healthy, but `/api/database` returns frontend content or a frontend 404. Inspecting the Ingress shows the incorrect backend.

## Fix and verify

```bash
kubectl -n production-lab patch ingress application --type=json \
  -p='[{"op":"replace","path":"/spec/rules/0/http/paths/0/backend/service/name","value":"backend"},{"op":"replace","path":"/spec/rules/0/http/paths/0/backend/service/port/number","value":8080}]'
curl -i "http://${ALB_HOST}/api/database"
```

Root cause: path order was correct, but the `/api` path referenced the frontend Service.

