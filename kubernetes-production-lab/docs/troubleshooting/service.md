# Exercise: Backend Service has no endpoints

## Introduce the failure

```bash
kubectl -n production-lab patch service backend --type=merge \
  -p='{"spec":{"selector":{"app.kubernetes.io/name":"backend-broken"}}}'
```

## Investigate

```bash
kubectl -n production-lab get service backend -o yaml
kubectl -n production-lab get endpointslices -l kubernetes.io/service-name=backend
kubectl -n production-lab get pods --show-labels
kubectl run curl --rm -it --restart=Never --image=curlimages/curl -- \
  curl -i http://backend.production-lab.svc.cluster.local:8080/api/health/ready
```

Expected evidence: the Service exists and DNS resolves, but its EndpointSlice has no endpoints because the selector matches no Pod.

## Fix and verify

```bash
kubectl -n production-lab patch service backend --type=merge \
  -p='{"spec":{"selector":{"app.kubernetes.io/name":"backend"}}}'
kubectl -n production-lab get endpointslices -l kubernetes.io/service-name=backend
```

Root cause: Service selectors are exact label matches; a healthy Deployment does not help if the Service selects the wrong labels.
