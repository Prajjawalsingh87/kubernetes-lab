# Self-managed kubeadm deployment

This overlay targets the EC2 kubeadm cluster, not EKS. Install ingress-nginx,
Metrics Server, and the AWS EBS CSI driver before applying it. Attach an EC2
instance role with `AmazonEC2ContainerRegistryReadOnly` to every Kubernetes
node so ECR images can be pulled without storing AWS keys in Kubernetes.

Create the ignored Secret input first:

```bash
cp secrets.env.example secrets.env
chmod 600 secrets.env
```

Set the ECR image tag in `kustomization.yaml`, preview the result, then deploy:

```bash
kubectl kustomize manifests/overlays/self-managed >/tmp/production-lab.yaml
kubectl apply --dry-run=server -f /tmp/production-lab.yaml
kubectl apply -k manifests/overlays/self-managed
```

Only the ingress-nginx NodePort is public. The frontend, backend, and
PostgreSQL Services remain ClusterIP Services.
