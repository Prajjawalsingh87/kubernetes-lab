# Exercise: PostgreSQL PVC stays Pending

## Introduce the failure

Use a disposable claim; do not alter the real database volume.

```bash
kubectl -n production-lab apply -f - <<'YAML'
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: broken-storage-test
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: does-not-exist
  resources:
    requests:
      storage: 1Gi
YAML
```

## Investigate

```bash
kubectl -n production-lab get pvc
kubectl -n production-lab describe pvc broken-storage-test
kubectl get storageclass
kubectl -n kube-system get pods -l app.kubernetes.io/name=aws-ebs-csi-driver
```

Expected evidence: the claim is `Pending`; events indicate that `does-not-exist` cannot provision a volume.

## Fix and verify

The StorageClass name of an existing PVC is immutable, so recreate only this disposable claim with the correct class:

```bash
kubectl -n production-lab delete pvc broken-storage-test
kubectl -n production-lab apply -f - <<'YAML'
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: fixed-storage-test
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: gp3-encrypted
  resources:
    requests:
      storage: 1Gi
YAML
kubectl -n production-lab get pvc fixed-storage-test
```

Because this StorageClass uses `WaitForFirstConsumer`, attach the corrected claim to a temporary Pod before expecting `Bound`:

```bash
kubectl -n production-lab apply -f - <<'YAML'
apiVersion: v1
kind: Pod
metadata:
  name: storage-consumer-test
spec:
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault
  tolerations:
    - key: dedicated
      operator: Equal
      value: postgres
      effect: NoSchedule
  nodeSelector:
    workload: postgres
  containers:
    - name: test
      image: busybox:1.36
      command: [sh, -c, 'echo storage-ok > /data/result && sleep 3600']
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: [ALL]
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: fixed-storage-test
YAML
kubectl -n production-lab get pod storage-consumer-test
kubectl -n production-lab get pvc fixed-storage-test
kubectl -n production-lab exec storage-consumer-test -- cat /data/result
kubectl -n production-lab delete pod storage-consumer-test
kubectl -n production-lab delete pvc fixed-storage-test
```

Root cause: the claim referenced a StorageClass that did not exist. Never delete the production PVC during this exercise because its `Retain` policy intentionally preserves the EBS volume.
