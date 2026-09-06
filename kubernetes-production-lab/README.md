# Self-managed Kubernetes production lab

This repository deploys the frontend, FastAPI backend, and PostgreSQL on a
self-managed `kubeadm` cluster running on EC2. It does not use EKS or
Terraform.

The manifests implement a namespace, Deployments with requests/limits and
probes, ConfigMap, Secret generation, internal Services, nginx Ingress,
PostgreSQL PV/PVC, backend HPA, rolling updates for FE/BE, Recreate for
PostgreSQL, PDBs, NetworkPolicy, and PostgreSQL node taint/toleration/affinity.
See [docs/architecture.md](docs/architecture.md) and
[evidence/README.md](evidence/README.md).

## Prerequisites

Use one kubeadm control plane and three workers with Calico installed and all
nodes `Ready`. Install `kubectl` and Helm 3 on the control plane. For private
ECR images, attach an EC2 instance profile containing
`AmazonEC2ContainerRegistryReadOnly` to every node.

## Prepare nodes

```bash
kubectl label node <worker-1> workload=application
kubectl label node <worker-2> workload=application
kubectl label node <worker-3> workload=postgres
kubectl taint node <worker-3> dedicated=postgres:NoSchedule
```

## Install add-ons

Only the nginx Ingress NodePort is public; application Services remain
`ClusterIP`:

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --set controller.service.type=NodePort \
  --set controller.service.nodePorts.http=30080
```

Install Metrics Server for the HPA (the insecure kubelet option is for this
isolated lab only):

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch deployment metrics-server -n kube-system --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
```

Install the AWS EBS CSI driver and grant its controller an IAM role before
using the `ebs.csi.aws.com` StorageClass in `manifests/base/storage.yaml`.

## Build and publish images

From a workstation with Docker and AWS CLI authenticated in `us-east-1`:

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export IMAGE_TAG=$(git rev-parse --short HEAD)
aws ecr create-repository --region "$AWS_REGION" --repository-name production-lab-frontend 2>/dev/null || true
aws ecr create-repository --region "$AWS_REGION" --repository-name production-lab-backend 2>/dev/null || true
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
docker build -t "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/production-lab-frontend:$IMAGE_TAG" frontend
docker build -t "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/production-lab-backend:$IMAGE_TAG" backend
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/production-lab-frontend:$IMAGE_TAG"
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/production-lab-backend:$IMAGE_TAG"
```

Edit `manifests/overlays/self-managed/kustomization.yaml`, replacing
`AWS_ACCOUNT_ID` and `IMAGE_TAG` with the values above. Prefer immutable Git
tags or image digests for releases.

## Deploy

```bash
cd manifests/overlays/self-managed
cp secrets.env.example secrets.env
chmod 600 secrets.env
$EDITOR secrets.env
cd ../../..

kubectl kustomize manifests/overlays/self-managed >/tmp/production-lab.yaml
kubectl apply --dry-run=server -f /tmp/production-lab.yaml
kubectl apply -k manifests/overlays/self-managed
```

To use another namespace, change `namespace:` in the self-managed
`kustomization.yaml` and the Namespace name in `manifests/base/namespace.yaml`
to the same value. Never commit `secrets.env`.

Verify:

```bash
kubectl -n production-lab rollout status deployment/postgres --timeout=5m
kubectl -n production-lab rollout status deployment/backend --timeout=5m
kubectl -n production-lab rollout status deployment/frontend --timeout=5m
kubectl -n production-lab get deploy,rs,pods,svc,ingress,hpa,pvc -o wide
kubectl get pv
kubectl top pods -n production-lab
```

Access through a worker public IP on NodePort `30080`:

```bash
curl -i http://<worker-public-ip>:30080/
curl -i http://<worker-public-ip>:30080/api/health/ready
```

Allow TCP 30080 in the EC2 security group. Do not expose backend 8080 or
PostgreSQL 5432 publicly.

## Autoscaling and troubleshooting

The backend HPA requires Metrics Server. Cluster Autoscaler requires an EC2
Auto Scaling Group with discovery tags and IAM permissions; manually launched
instances are not an ASG. Keep PostgreSQL outside the scalable ASG. Failure
exercises are in `docs/troubleshooting/`; evidence requirements are in
`evidence/README.md`.

## Cleanup

```bash
kubectl delete -k manifests/overlays/self-managed
```

Terminate EC2 instances when finished to avoid charges.
