# Kubernetes Production Lab on Amazon EKS

This repository deploys a static NGINX frontend, a FastAPI backend, and PostgreSQL to Amazon EKS. It starts with **three EC2 worker nodes**: two general application workers and one tainted PostgreSQL worker. Amazon EKS supplies the managed, multi-AZ control plane; you should not run a single production control-plane EC2 instance yourself.

The application uses production-oriented Kubernetes controls while remaining small enough for a temporary lab. It is not a highly available production database design: the assignment explicitly asks for PostgreSQL as a Kubernetes `Deployment`. For a real production system, use Amazon RDS/Aurora Multi-AZ or a PostgreSQL operator with replication, backups, and tested restore procedures.

## What is included

| Requirement | Implementation |
|---|---|
| Namespace | `production-lab`, with restricted Pod Security admission labels |
| FE, BE, PostgreSQL | Deployments with requests/limits and health probes |
| Configuration | ConfigMap for non-sensitive settings; Kustomize-generated Secret from an ignored local file |
| Networking | Three internal `ClusterIP` Services and one public ALB Ingress |
| Routing | `/` -> frontend; `/api` -> backend; PostgreSQL has no external route |
| Storage | Encrypted gp3 StorageClass, PVC, and dynamically provisioned PV with `Retain` |
| Pod autoscaling | Backend HPA, 2-10 replicas, CPU and memory targets |
| Node autoscaling | Cluster Autoscaler, application node group 2-6 nodes |
| PostgreSQL isolation | Dedicated fixed-size node group, taint, toleration, and required node affinity |
| Rollouts | Zero-unavailable rolling updates for FE/BE; `Recreate` for single-writer PostgreSQL/EBS |
| Availability | Two FE/BE replicas, soft pod anti-affinity, PodDisruptionBudgets |
| Network isolation | VPC CNI network-policy mode; PostgreSQL accepts traffic only from backend Pods |
| Troubleshooting | Scheduling, Service, Ingress, and storage exercises with fixes |

See [the architecture diagram](docs/architecture.md) and [the evidence checklist](evidence/README.md).

## Repository layout

```text
frontend/                   Frontend image source
backend/                    FastAPI image source
infrastructure/             eksctl cluster and Helm values/IAM policy
manifests/base/             Portable Kubernetes resources
manifests/overlays/aws/     AWS images, TLS Ingress, and local Secret generation
docs/troubleshooting/       Reproducible failure investigations and fixes
evidence/                   Screenshot/output checklist
```

## 1. Prerequisites and cost warning

Install and authenticate these tools:

- AWS CLI v2 (`aws sts get-caller-identity` must succeed)
- `eksctl` 0.215.0 or newer
- `kubectl`
- Helm 3
- Docker
- `jq`
- an ACM certificate in `ap-south-1` and a DNS name you control

This lab incurs charges for the EKS cluster, three EC2 instances, NAT gateway/data, ALB, EBS, and public IPv4/DNS where applicable. EKS alone has a per-cluster hourly charge, and worker nodes are billed as normal EC2 instances. Delete the lab when finished.

The committed configuration uses `t3.medium` only to control temporary lab cost. For a real production baseline, benchmark first and use non-burstable general-purpose nodes (for example M-family) and an appropriate memory-optimized database node.

Set local shell variables:

```bash
export AWS_REGION=ap-south-1
export CLUSTER_NAME=production-lab
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export IMAGE_TAG=$(git rev-parse --short HEAD)
```

## 2. Create ECR repositories and push images

Create the repositories once:

```bash
aws ecr create-repository --region "$AWS_REGION" \
  --repository-name production-lab-frontend \
  --image-scanning-configuration scanOnPush=true \
  --image-tag-mutability IMMUTABLE

aws ecr create-repository --region "$AWS_REGION" \
  --repository-name production-lab-backend \
  --image-scanning-configuration scanOnPush=true \
  --image-tag-mutability IMMUTABLE
```

Authenticate, build, and push immutable application versions:

```bash
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin \
  "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

docker build -t "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/production-lab-frontend:$IMAGE_TAG" frontend
docker build -t "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/production-lab-backend:$IMAGE_TAG" backend

docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/production-lab-frontend:$IMAGE_TAG"
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/production-lab-backend:$IMAGE_TAG"
```

Review ECR scan findings before deployment. In stricter production CI, fail builds on an agreed severity threshold and pin every base image by digest.

## 3. Create EKS and the initial three workers

Review the region, Availability Zones, instance types, and limits in `infrastructure/eks-cluster.yaml`, then run:

```bash
eksctl create cluster -f infrastructure/eks-cluster.yaml
kubectl get nodes -L workload -o wide
```

Expected initial state: two nodes labeled `workload=application` and one node labeled `workload=postgres`. The PostgreSQL node is tainted `dedicated=postgres:NoSchedule` and pinned to `ap-south-1a`. All workers use private subnets; `eksctl` creates the VPC networking needed by this lab.

The EBS CSI driver and Metrics Server are EKS add-ons declared in the cluster configuration. Confirm both before continuing:

```bash
eksctl get addon --cluster "$CLUSTER_NAME" --region "$AWS_REGION"
kubectl top nodes
```

## 4. Install AWS Load Balancer Controller

Use a controller release supported by your EKS/Kubernetes version. The example variable must be deliberately set rather than silently using an unreviewed release:

```bash
export LBC_VERSION=v2.14.1

curl -fsSLo /tmp/aws-load-balancer-controller-iam-policy.json \
  "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/${LBC_VERSION}/docs/install/iam_policy.json"

aws iam create-policy \
  --policy-name AWSLoadBalancerControllerIAMPolicy-production-lab \
  --policy-document file:///tmp/aws-load-balancer-controller-iam-policy.json

eksctl create iamserviceaccount \
  --cluster "$CLUSTER_NAME" --region "$AWS_REGION" \
  --namespace kube-system --name aws-load-balancer-controller \
  --attach-policy-arn "arn:aws:iam::$AWS_ACCOUNT_ID:policy/AWSLoadBalancerControllerIAMPolicy-production-lab" \
  --override-existing-serviceaccounts --approve

helm repo add eks https://aws.github.io/eks-charts
helm repo update
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --namespace kube-system \
  --values infrastructure/aws-load-balancer-controller-values.yaml
```

If the named IAM policy already exists, inspect and reuse/update it instead of running `create-policy` again.

## 5. Install Cluster Autoscaler with least-privilege IRSA

Create the account policy from the committed policy document. Its scale actions are limited by the two cluster discovery tags:

```bash
aws iam create-policy \
  --policy-name ClusterAutoscalerPolicy-production-lab \
  --policy-document file://infrastructure/cluster-autoscaler-iam-policy.json

eksctl create iamserviceaccount \
  --cluster "$CLUSTER_NAME" --region "$AWS_REGION" \
  --namespace kube-system --name cluster-autoscaler \
  --attach-policy-arn "arn:aws:iam::$AWS_ACCOUNT_ID:policy/ClusterAutoscalerPolicy-production-lab" \
  --override-existing-serviceaccounts --approve

export K8S_MINOR=$(kubectl version -o json | jq -r '.serverVersion | "\(.major).\(.minor | sub("\\+.*$"; ""))"')

helm repo add autoscaler https://kubernetes.github.io/autoscaler
helm repo update
helm upgrade --install cluster-autoscaler autoscaler/cluster-autoscaler \
  --namespace kube-system \
  --values infrastructure/cluster-autoscaler-values.yaml \
  --set "image.tag=v${K8S_MINOR}.0"
```

Cluster Autoscaler must match the cluster's Kubernetes major/minor version. Confirm the selected image tag exists and review the current compatibility documentation before installing. It changes only the application group's desired capacity between 2 and 6; the database group remains fixed at 1.

## 6. Configure TLS, images, and the Secret

Copy the ignored Secret input and replace both values. Never commit this file:

```bash
cp manifests/overlays/aws/secrets.env.example manifests/overlays/aws/secrets.env
chmod 600 manifests/overlays/aws/secrets.env
```

Edit `manifests/overlays/aws/kustomization.yaml`:

- replace `AWS_ACCOUNT_ID` with your account ID;
- replace both `IMAGE_TAG` values with the Git-based image tag pushed above.

Edit `manifests/overlays/aws/ingress-patch.yaml`:

- replace `APP_DOMAIN` with your DNS name, such as `lab.example.com`;
- replace `ACM_CERTIFICATE_ARN` with an issued ACM certificate ARN from `ap-south-1`.

Kustomize generates the Kubernetes Secret locally and rewrites references to its hashed name. PostgreSQL credentials are therefore not hardcoded in Git, and changing them produces a rollout-triggering name change. For a long-running production system, use AWS Secrets Manager with External Secrets or the Secrets Store CSI driver and define a rotation procedure.

Preview before applying:

```bash
kubectl kustomize manifests/overlays/aws >/tmp/production-lab-rendered.yaml
kubectl apply --dry-run=server -f /tmp/production-lab-rendered.yaml
```

Do not commit or share the rendered file because it contains the generated Secret.

## 7. Deploy and configure DNS

```bash
kubectl apply -k manifests/overlays/aws
kubectl -n production-lab rollout status deployment/postgres --timeout=5m
kubectl -n production-lab rollout status deployment/backend --timeout=5m
kubectl -n production-lab rollout status deployment/frontend --timeout=5m
kubectl -n production-lab get deploy,rs,pods,svc,ingress,hpa,pdb,pvc -o wide
kubectl get pv
```

Wait for the ALB hostname:

```bash
kubectl -n production-lab get ingress application --watch
```

Create a Route 53 alias record from your application domain to that ALB. Then verify:

```bash
curl -i "https://APP_DOMAIN/"
curl -i "https://APP_DOMAIN/api/health/ready"
curl -i "https://APP_DOMAIN/api/database"
```

Only the ALB is public. The frontend, backend, and PostgreSQL Services are all `ClusterIP`. The backend is reachable only through the ALB's intentional `/api` route; PostgreSQL is cluster-internal only.

## 8. Demonstrate pod and node autoscaling

Generate temporary CPU pressure against the backend (use a controlled lab only). This runs in the `default` namespace because the application namespace enforces the restricted Pod Security profile:

```bash
kubectl create deployment load-generator --image=busybox:1.36 -- \
  /bin/sh -c 'while true; do wget -q -O- http://backend.production-lab.svc.cluster.local:8080/api/database >/dev/null; done'
kubectl scale deployment load-generator --replicas=10
```

Watch the two levels separately:

```bash
kubectl -n production-lab get hpa backend --watch
kubectl -n production-lab get pods --watch
kubectl get nodes --watch
kubectl -n kube-system logs deployment/cluster-autoscaler -f
```

The HPA first adds backend Pods. At the upper range, their 500m CPU requests exceed the two-node baseline, Pods become Pending, and Cluster Autoscaler increases the `application-workers` Auto Scaling group. Scale-down is intentionally slower to prevent flapping. Stop the test with `kubectl delete deployment load-generator`.

## 9. Deployment strategy

Frontend and backend use `RollingUpdate` with `maxUnavailable: 0` and `maxSurge: 1`, readiness gating, `minReadySeconds`, two baseline replicas, and PDBs. This is the best fit for a stateless small application: no second production stack is required, and a failed revision can be stopped or undone:

```bash
kubectl -n production-lab rollout history deployment/backend
kubectl -n production-lab rollout undo deployment/backend
```

PostgreSQL uses `Recreate`, because one ReadWriteOnce EBS volume must not be mounted by two database Pods during an update. Blue-green or canary releases are more appropriate when schema compatibility and traffic splitting have been engineered and tested; adding those labels alone would not make this database safe.

## 10. Troubleshooting exercises

Run one failure at a time, record before/during/after evidence, apply its fix, and confirm the application is healthy before starting the next:

- [Pod scheduling](docs/troubleshooting/pod-scheduling.md)
- [Service selectors/endpoints](docs/troubleshooting/service.md)
- [Ingress routing](docs/troubleshooting/ingress.md)
- [Persistent storage](docs/troubleshooting/storage.md)

## 11. Production hardening beyond the assignment

- Replace in-cluster PostgreSQL with RDS/Aurora Multi-AZ, or add a PostgreSQL operator, replicas, automated backups, EBS snapshots, and restore testing.
- Expand NetworkPolicies to default-deny ingress/egress after documenting every required flow; add WAF, Route 53, ACM renewal monitoring, and ALB access logs.
- Restrict the EKS public API endpoint to trusted CIDRs or private access paths.
- Add CloudWatch/Prometheus metrics, centralized logs, alerts, audit logging, and SLOs.
- Use GitHub Actions/OIDC rather than permanent AWS keys; scan images and manifests; sign images and enforce admission policy.
- Use topology spread constraints and at least three application nodes for stronger zone-failure tolerance.

## 12. Clean up

First remove the application so the controller can delete the ALB, then delete the cluster:

```bash
kubectl delete -k manifests/overlays/aws
kubectl -n production-lab get ingress
eksctl delete cluster -f infrastructure/eks-cluster.yaml
```

Because the StorageClass uses `Retain`, inspect and explicitly delete the retained EBS volume only after confirming its data is no longer needed. Also delete the two ECR repositories, Route 53 record, ACM certificate if dedicated to the lab, and custom IAM policies if they are no longer used.

## Why each Kubernetes object exists

- **Namespace**: scope, ownership, policy boundary, and simpler cleanup.
- **ConfigMap**: non-secret runtime configuration without rebuilding images.
- **Secret**: credentials separated from code and generated outside Git.
- **Deployment/ReplicaSet**: declarative rollout, reconciliation, replica count, and rollback.
- **Service**: stable DNS/virtual IP while Pod IPs change.
- **Ingress**: one public HTTP(S) entry point and path-based routing.
- **StorageClass/PVC/PV**: a portable storage request backed by an encrypted EBS volume; `WaitForFirstConsumer` prevents an Availability Zone mismatch.
- **HPA**: scales backend replicas based on measured utilization relative to resource requests.
- **Cluster Autoscaler**: adds/removes EC2 worker capacity for unschedulable/underutilized Pods.
- **Taint/toleration/affinity**: reserves the database node and explicitly places PostgreSQL there.
- **PDB**: limits voluntary disruption during node drains and maintenance.
- **NetworkPolicy**: limits PostgreSQL ingress to backend Pods when VPC CNI network-policy mode is enabled.
