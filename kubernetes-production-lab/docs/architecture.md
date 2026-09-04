# Kubernetes architecture

```mermaid
flowchart TB
  U[Internet user] --> ALB[Public AWS Application Load Balancer]

  subgraph EKS[Amazon EKS cluster]
    CP[AWS-managed highly available control plane]
    ALBC[AWS Load Balancer Controller]
    CA[Cluster Autoscaler]
    MS[Metrics Server]

    ALB --> ING[Ingress: / to frontend, /api to backend]
    ING --> FES[Frontend ClusterIP Service]
    ING --> BES[Backend ClusterIP Service]
    BES --> BERS[Backend ReplicaSet]
    FES --> FERS[Frontend ReplicaSet]

    subgraph APPNG[Application managed node group: 2 to 6 nodes]
      FED[Frontend Deployment] --> FERS
      FERS --> FE1[Frontend Pod]
      FERS --> FE2[Frontend Pod]
      BED[Backend Deployment] --> BERS
      BERS --> BE1[Backend Pod]
      BERS --> BE2[Backend Pod]
    end

    HPA[Backend HPA: 2 to 10 Pods] --> BED
    MS --> HPA
    HPA -. pending Pods .-> CA
    CA --> APPNG

    BE1 --> PGS[PostgreSQL ClusterIP Service]
    BE2 --> PGS

    subgraph DBNG[Dedicated PostgreSQL node: tainted, fixed at 1]
      PGD[PostgreSQL Deployment: Recreate] --> PGRS[PostgreSQL ReplicaSet]
      PGRS --> PGP[PostgreSQL Pod with toleration and node affinity]
    end

    PGS --> PGP
    PGP --> PVC[PersistentVolumeClaim: 10 GiB]
    PVC --> PV[Dynamically provisioned PersistentVolume]
  end

  PV --> EBS[Encrypted gp3 EBS volume, Retain policy]
  CP -. reconciles .-> FED
  CP -. reconciles .-> BED
  CP -. reconciles .-> PGD
  ALBC -. provisions .-> ALB
```

## Design notes

- EKS operates the control plane across multiple Availability Zones; it is not a fourth EC2 instance managed by this project.
- The initial data plane is three EC2 workers: two application nodes and one fixed, dedicated PostgreSQL node.
- `Deployment -> ReplicaSet -> Pod` ownership is shown explicitly. Services select Pods by labels; they do not route to Deployments.
- The ALB is the only public entry point. Every Kubernetes Service is `ClusterIP`; PostgreSQL has no public route.
- The HPA creates/removes backend Pods. Cluster Autoscaler reacts only when Pods cannot be scheduled and changes the application node group's desired capacity.
- The PVC dynamically creates the PV through the EBS CSI driver. `WaitForFirstConsumer` aligns the EBS volume Availability Zone with the PostgreSQL node.

