# Deployment

## Local

```
brew install tesseract redis
uv sync
cp .env.example .env
uv run uvicorn services.api.app.main:app --port 7441 --reload
uv run python -m services.worker.app.main    # second shell
cd web && npm install && npm run dev          # third shell
```

## Docker compose

```
cd infra/docker
docker compose -f docker-compose.dev.yml up --build
```

This spins up Postgres, Redis, API, worker, and web. Set `LLM_BASE_URL` to a reachable OpenAI-compatible endpoint. On macOS the default value points at `host.docker.internal:4141` which works with the GitHub Copilot proxy.

## Kubernetes

```
helm install shotclassify infra/helm/shotclassify \
  --set image.api.tag=$(git rev-parse --short HEAD) \
  --set secret.apiKey=$(openssl rand -hex 16)
```

## AWS bucket for blobs

```
cd infra/terraform
terraform init
terraform plan -var-file terraform.tfvars
```

Outputs `bucket_name` and `iam_user`. Wire credentials to the API pod via a Kubernetes secret, then set `STORAGE_BACKEND=s3` and `STORAGE_S3_BUCKET`.
