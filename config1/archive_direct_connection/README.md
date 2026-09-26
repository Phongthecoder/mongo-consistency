# Configuration 1 (archived direct-connection version)

> **Archived.** This is the earlier version of Configuration 1. Its scripts ran on the
> host with three independent direct connections (`directConnection=True`), so writes
> were pinned to mongo1 with no failover. It was replaced by the version in the parent
> directory, which uses the same replica-set client, container and test harness as
> Configuration 2 so that the two configurations differ only in their settings. The
> scripts and results here are kept for reference. To run them, `cd` into this directory
> instead of `config1/`.

Write concern **w=1**, read concern **local**, read preference **secondary**,
and causal consistency **OFF**. No session is used.

- [Experiment summary](config1_summary.md)

## Requirements

Python 3.9 or later on the host, Docker with Compose, and the base compose.yaml in
this repository. The scripts run on the host and connect directly to each node through
the published ports: mongo1 on 27017, mongo2 on 27018 and mongo3 on 27019.
Ports 27017–27019 and container names mongo1–mongo3 must be available.

## Deployment

Clone this repository, then run from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

docker-compose -f compose.yaml up -d
.venv/bin/python setup_majority.py
```

setup_majority.py initializes or checks replica set rs0 and verifies that mongo1 is
PRIMARY (priority 2) and mongo2/mongo3 are SECONDARY. Configuration 1 needs no
further setup. The fault scripts call `docker` directly, so the current Docker
context must be the one running the containers.

## Experiments

Run only one scenario at a time, from the config1/ directory (`cd config1`). Fault
scripts stop mongo2 or disconnect mongo1 from the project network and restore the
cluster afterwards.

```bash
# Short preflight runs (3 trials per model per phase; results files are not written)
../.venv/bin/python normal_config1_experiment.py --smoke
../.venv/bin/python node_failure_config1_experiment.py --smoke
../.venv/bin/python network_partition_config1_experiment.py --smoke

# Formal runs
../.venv/bin/python normal_config1_experiment.py
../.venv/bin/python node_failure_config1_experiment.py
../.venv/bin/python network_partition_config1_experiment.py
```

Formal sample sizes are 1,000 trials per model under normal operation, 500 per model
in each node-failure/recovery phase, and 60 per model in each partition/recovery phase:
8,480 total. The optional test_ryw_config1.py is excluded from that total.

Each formal run writes its counts to normal_config1_results.json,
node_failure_config1_results.json or network_partition_config1_results.json in this
directory, overwriting the previous file.

## Published results and reproducibility

config1_summary.md describes the results files committed in this directory. A new run
may observe different violation counts, because they depend on replication timing on the
host; exact outcome counts are not deterministic. No per-operation history is recorded
for Configuration 1, only the per-model counts.

The mongo:8 tag is floating; future image pulls may resolve to a different MongoDB
version.
