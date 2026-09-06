# Ingress troubleshooting

The self-managed cluster uses ingress-nginx exposed through NodePort `30080`.
The AWS ALB controller is not required.

## Intentional failure

Change `spec.ingressClassName` from `nginx` to a nonexistent class, apply the
manifest, and observe that the Ingress receives no controller address.

```bash
kubectl -n production-lab get ingress application
kubectl -n ingress-nginx logs deployment/ingress-nginx-controller
curl -i http://<worker-public-ip>:30080/
```

## Fix

Restore `ingressClassName: nginx`, apply the self-managed overlay, and verify
that the NodePort routes `/` to frontend and `/api` to backend:

```bash
kubectl apply -k manifests/overlays/self-managed
kubectl -n production-lab describe ingress application
curl -i http://<worker-public-ip>:30080/
curl -i http://<worker-public-ip>:30080/api/health/ready
```
