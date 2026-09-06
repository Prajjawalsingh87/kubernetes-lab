# Self-managed Kubernetes architecture

```mermaid
flowchart TB
  U[Internet user] --> NGINX[ingress-nginx NodePort 30080]
  subgraph EC2[Self-managed kubeadm cluster]
    CP[Control-plane EC2\nAPI server / scheduler / controllers / etcd]
    MS[Metrics Server] --> HPA[Backend HPA 2-10]
    HPA --> BD[Backend Deployment]
    CA[Cluster Autoscaler\noptional ASG integration] -. scales .-> ASG[Application Auto Scaling Group]
    subgraph APP[Application workers]
      FD[Frontend Deployment] --> FRS[Frontend ReplicaSet]
      FRS --> FP1[Frontend Pod]
      FRS --> FP2[Frontend Pod]
      BD --> BRS[Backend ReplicaSet]
      BRS --> BP1[Backend Pod]
      BRS --> BP2[Backend Pod]
    end
    subgraph DB[Dedicated PostgreSQL worker\nlabel workload=postgres\ntaint dedicated=postgres:NoSchedule]
      PD[PostgreSQL Deployment\nRecreate] --> PRS[PostgreSQL ReplicaSet]
      PRS --> PP[PostgreSQL Pod\ntoleration + node affinity]
      PP --> PVC[PVC 10Gi]
      PVC --> PV[PV]
      PV --> EBS[Encrypted EBS volume]
    end
    NGINX --> FES[Frontend ClusterIP Service]
    NGINX --> BES[Backend ClusterIP Service]
    BES --> BP1
    FES --> FP1
    BP1 --> PGS[PostgreSQL ClusterIP Service]
    PGS --> PP
    CP -. manages .-> FD
    CP -. manages .-> BD
    CP -. manages .-> PD
  end
```

The Ingress NodePort is the only public entry point. Backend and PostgreSQL
Services are ClusterIP-only. Deployments own ReplicaSets, ReplicaSets own
Pods, the HPA changes backend replica count, and the node autoscaler changes
only an application ASG when configured. PostgreSQL uses a single-writer
Recreate strategy and retained persistent storage; a production database needs
replication, backups, and restore testing.
