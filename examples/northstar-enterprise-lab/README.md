# Northstar synthetic enterprise lab

A local Superset lab for the fictional Northstar Outfitters retailer. It generates synthetic business data; it includes no warehouse dump, customer data, cards, or analyst playbooks.

## Start locally

Requirements: Docker Desktop with Compose and Python 3.10+. From the repository checkout:

```bash
cd examples/northstar-enterprise-lab
python3 scripts/generate_enterprise.py
export NORTHSTAR_WAREHOUSE_PASSWORD="$(openssl rand -hex 24)"
export NORTHSTAR_SUPERSET_DB_PASSWORD="$(openssl rand -hex 24)"
export NORTHSTAR_SUPERSET_ADMIN_PASSWORD="$(openssl rand -hex 24)"
export NORTHSTAR_SUPERSET_SECRET_KEY="$(openssl rand -hex 32)"
printf 'Superset username: admin\nPassword (keep private): %s\n' "$NORTHSTAR_SUPERSET_ADMIN_PASSWORD"
docker compose --project-name northstar-enterprise-lab up -d
```

The credentials stay in your shell environment; no `.env` file is created. Superset binds to `127.0.0.1:18090` by default. The project uses its own network and named volumes; stop its containers with `docker compose --project-name northstar-enterprise-lab down` (volumes are retained).

## What it seeds

The deterministic generator (seed `90219`) produces 16 synthetic tables totaling 828,883 rows. Superset seeding creates 24 datasets, 1,200 charts, and 48 dashboards. Generated CSVs and initialization SQL stay in the ignored `warehouse/init/` directory; only the small manifests are packaged.

## Verification boundary

A complete seed was verified on a locally cached Superset-derived image. A fresh build from the pinned Dockerfile is still unverified, so the cached run is not proof of a clean image build. See the [reproduction record](docs/reproduction.md) for results, provenance, and the full attempt history.
