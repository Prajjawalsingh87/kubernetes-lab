# CI/CD for the self-managed cluster

The workflow in `.github/workflows/deploy.yml` runs on pushes to
`setup/initial-architecture` (and can also be started manually).

1. GitHub Actions authenticates to AWS using GitHub OIDC; no AWS root keys are stored in GitHub.
2. Frontend and backend images are built and pushed to ECR with the short commit SHA as an immutable tag.
3. A self-hosted runner on the Kubernetes control-plane refreshes the ECR pull Secret.
4. Kustomize substitutes the new image tag and applies the self-managed overlay.
5. Rollout status is checked for frontend, backend, and PostgreSQL.

## One-time setup

Create an IAM role trusted by GitHub's OIDC provider. Restrict its trust policy to
this repository and branch, and grant only ECR push permissions for the two
repositories. Store the role ARN as the GitHub repository secret
`AWS_GITHUB_ACTIONS_ROLE_ARN`.

Install a GitHub self-hosted runner on the control-plane and give it the labels
`self-hosted`, `linux`, and `k8s-control-plane`. The runner user must have a
working kubeconfig and access to `kubectl`, `kustomize`, and AWS CLI. Add the
repository secrets `DB_USER` and `DB_PASSWORD`; the workflow materializes the
ignored `secrets.env` file during each deployment.

## Triggering a deployment

Commit and push application changes:

```bash
git add backend frontend manifests .github/workflows/deploy.yml
git commit -m "feat: change application"
git push origin setup/initial-architecture
```

The workflow creates a new image tag, performs a rolling update for frontend and
backend, and fails if the rollout or health checks do not complete.
