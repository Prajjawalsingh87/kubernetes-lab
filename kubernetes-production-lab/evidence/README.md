# Evidence checklist

Do not commit credentials or kubeconfig. Capture these after the live deployment and place screenshots here (ignored by Git by default unless you explicitly force-add selected images).

1. `kubectl get nodes -L workload -o wide` — three initial workers and their roles.
2. `kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints` — PostgreSQL taint.
3. `kubectl -n production-lab get deploy,rs,pods,svc,ingress,hpa,pdb,pvc -o wide`.
4. `kubectl get pv` and `kubectl get storageclass gp3-encrypted -o yaml`.
5. `kubectl -n production-lab describe deployment backend` — requests, limits, probes, and rolling strategy.
6. `kubectl -n production-lab describe pod -l app.kubernetes.io/name=postgres` — affinity and toleration.
7. Browser showing the frontend and successful database response.
8. HPA load test: `kubectl -n production-lab get hpa backend --watch`.
9. Node scaling: EC2 Auto Scaling group activity plus `kubectl get nodes --watch`.
10. Before/failure/after output for every troubleshooting exercise.

Save text output in a report outside the public repository if it contains AWS account IDs, private IPs, or load-balancer hostnames. Redact those values before submission.

