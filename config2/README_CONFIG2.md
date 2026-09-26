# Configuration 2: deployment and reproduction

Write concern **majority**, read concern **majority**, read preference **secondary**,
and causal consistency **ON**. Related operations share one explicit causal session.

- [Concise report](configuration2_report.md)
- [Styled report](configuration2_report.html): download and open locally; figures are embedded.
- [Experiment summary](config2_summary.md)
- [Predictions](config2_plan.md)

## Requirements

Python 3.9 or later on the host, Docker with Compose, and the base compose.yaml in
this repository. The client image installs Python 3.12 and PyMongo 4.16.0.
Ports 27017–27019 and container names mongo1–mongo3 must be available.
The published code uses the new config2 names. Existing databases need not be deleted.

## Deployment

Clone this repository and check out runze, then run from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# For the macOS Colima environment used in the report:
colima start --profile consistency-lab
export DOCKER_CONTEXT=colima-consistency-lab

docker-compose -f compose.yaml up -d
.venv/bin/python setup_majority.py

docker-compose -f compose.yaml -f config2/compose.config2.yaml up -d --build client-config2
.venv/bin/python config2/setup_config2.py
```

On Docker Desktop or Linux, select the appropriate Docker context instead of running
the Colima commands. The launchers require the `docker-compose` executable; ensure it is installed and available on PATH.
The setup_majority.py and majority_config.py files at the repository root are shared
dependencies of the base replica-set bootstrap; the Configuration 2 experiments use config2/config2.py.

## Experiments

Run only one scenario at a time, from the config2/ directory (`cd config2`). Fault scripts stop mongo2 or disconnect mongo1 from
the project network and restore the cluster afterwards.

```bash
# Short preflight runs
../.venv/bin/python normal_config2_experiment.py --smoke
../.venv/bin/python node_failure_config2_experiment.py --smoke
../.venv/bin/python network_partition_config2_experiment.py --smoke

# Formal runs
../.venv/bin/python normal_config2_experiment.py
../.venv/bin/python node_failure_config2_experiment.py
../.venv/bin/python network_partition_config2_experiment.py

# Audit each printed output directory
../.venv/bin/python audit_config2.py results_config2/<run-directory>
```

Formal sample sizes are 1,000 trials per model under normal operation, 500 per model
in each node-failure/recovery phase, and 60 per model in each partition/recovery phase:
8,480 total. The optional test_ryw_config2.py is excluded from that total.
Allow approximately 20–40 minutes, depending on timeout behavior.

The launcher copies code into the client container. Each run saves source snapshots,
operation histories, summaries, database logs, and a completion marker. The audit
checks concern settings, causal sessions, routing, classifications and source hashes.

## Published results and reproducibility

The report describes the archived 23 September 2026 runs. Renaming files did not rerun
the experiments. A new run may elect a different primary or encounter different
transient timeouts; exact outcome counts are not deterministic. The full historical
operation logs are retained locally and are not included in this upload.

The mongo:8 and python:3.12-slim tags are floating. The report records the versions
used in the original experiment; future image pulls may resolve to different versions.
