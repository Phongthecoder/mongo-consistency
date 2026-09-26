# Configuration 1: deployment and reproduction

Write concern **w=1**, read concern **local**, read preference **secondary**,
and causal consistency **OFF**. No explicit session is used.

- [Experiment summary](config1_summary.md)
- [Predictions](config1_plan.md)
- [Earlier direct-connection version](archive_direct_connection/README.md)

## Requirements

Python 3.9 or later on the host, Docker with Compose, and the base compose.yaml in
this repository. The client image installs Python 3.12 and PyMongo 4.16.0, the same
image definition as Configuration 2.
Ports 27017–27019 and container names mongo1–mongo3 must be available.

## Deployment

Clone this repository, then run from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

docker-compose -f compose.yaml up -d
.venv/bin/python setup_majority.py

docker-compose -f compose.yaml -f config1/compose.config1.yaml up -d --build client-config1
.venv/bin/python config1/setup_config1.py
```

Select the Docker context that runs the containers before these commands. The launchers
require the `docker-compose` executable; ensure it is installed and available on PATH.
setup_config1.py adds the node tags (`node: mongo1/mongo2/mongo3`) used for secondary
routing if they are not already present; Configuration 2 uses the same tags.

## Experiments

Run only one scenario at a time, from the config1/ directory (`cd config1`). Fault
scripts stop mongo2 or disconnect mongo1 from the project network and restore the
cluster afterwards.

```bash
# Short preflight runs
../.venv/bin/python normal_config1_experiment.py --smoke
../.venv/bin/python node_failure_config1_experiment.py --smoke
../.venv/bin/python network_partition_config1_experiment.py --smoke

# Formal runs
../.venv/bin/python normal_config1_experiment.py
../.venv/bin/python node_failure_config1_experiment.py
../.venv/bin/python network_partition_config1_experiment.py

# Audit each printed output directory
../.venv/bin/python audit_config1.py results_config1/<run-directory>
```

Formal sample sizes are 1,000 trials per model under normal operation, 500 per model
in each node-failure/recovery phase, and 60 per model in each partition/recovery phase:
8,480 total. The optional test_ryw_config1.py is excluded from that total.

The launcher copies code into the client container. Each run saves source snapshots,
operation histories, summaries, database logs, and a completion marker. The audit
checks concern settings, the absence of causal sessions, routing, classifications and
source hashes.

## Published results and reproducibility

A new run may elect a different primary or encounter different transient timeouts;
exact outcome counts are not deterministic, and violation rates depend on replication
timing on the host.

The mongo:8 and python:3.12-slim tags are floating. Future image pulls may resolve to
different versions.
