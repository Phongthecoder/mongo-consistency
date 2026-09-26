# mongo-consistency

DSA5208 Project 1: how MongoDB's tunable consistency settings affect the four client-centric
consistency models (read-your-writes, monotonic reads, monotonic writes and writes-follow-reads)
under normal operation, a node failure and a network partition.

A three-node MongoDB replica set runs in Docker. Each configuration runs the same four tests in
the same way. The only differences between configurations are the write concern, the read concern
and the use of causal sessions.

| | Write concern | Read concern | Read preference | Causal consistency |
|---|---|---|---|---|
| **Configuration 1** | `w: 1` | `local` | secondary | OFF (no session) |
| **Configuration 2** | `w: "majority"` | `majority` | secondary | ON (one causal session per trial) |

## Repository layout

```text
mongo-consistency/
├── README.md                  this file
├── compose.yaml               the 3-node replica set (mongo1, mongo2, mongo3), shared by all configurations
├── setup_majority.py          initializes / checks replica set rs0 (shared)
├── majority_config.py         helpers used by setup_majority.py
├── requirements.txt           host Python dependencies (pymongo)
├── instruction.md             project brief
├── config3_summary.md         Configuration 3 results write-up (summary only; no code in this repository)
├── config1/                   Configuration 1: w=1 / local / causal OFF
│   ├── archive_direct_connection/   earlier Config 1 version (direct host connections), kept for reference
│   └── results_config1/             run directories (created by runs, not committed)
└── config2/                   Configuration 2: majority / majority / causal ON
    └── results_config2/             run directories (created by runs, not committed)
```

Both configuration folders contain the same set of files (replace `N` with `1` or `2`):

| File | Purpose |
|---|---|
| `configN.py` | The configuration: write concern, read concern, read preference, session settings |
| `normal_configN_experiment.py` | The four test functions (RYW, MR, MW, WFR) and the normal-operation entry point |
| `node_failure_configN.py` / `node_failure_configN_experiment.py` | Node-failure settings (stop `mongo2`) / entry point |
| `network_partition_configN.py` / `network_partition_configN_experiment.py` | Partition settings (disconnect `mongo1`) / entry point |
| `test_ryw_configN.py` | Optional standalone read-your-writes run (not part of the formal totals) |
| `configN_helpers.py` | Shared harness: container worker, trial execution, logging, fault recovery |
| `setup_configN.py` | Adds node tags to the replica set and records the deployment |
| `audit_configN.py` | Independently re-checks a finished run directory |
| `Dockerfile.configN`, `compose.configN.yaml` | The client container the tests run in |
| `configN_plan.md` | Predictions written before the experiments were run |
| `configN_summary.md` | Results and discussion |
| `README_CONFIGN.md` | Configuration-specific notes |
| `*_configN_results.json` | Counts from the latest formal run of each scenario, with the path to its run directory |

### How a run works

The test code runs **inside a client container** (`client-config1` or `client-config2`) on the same
Docker network as the database. It connects with one replica-set client:
`mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0`. Those host names only resolve
inside the Docker network. The script you start on the host is only a launcher. It copies the code
into the container, sends each trial to a worker process there, and performs the fault injection
itself (`docker stop`, `docker network disconnect`), because that has to happen outside the container.
Writes go to the current primary. Reads go to `mongo2` ("Secondary 1") or `mongo3` ("Secondary 2"),
selected by replica-set member tags.

## Requirements

- Docker with the `docker-compose` command on `PATH` (tested with Docker Desktop on macOS and Docker Compose v5.5.1)
- Python 3.9 or later on the host
- Free host ports 27017–27019 and container names `mongo1`–`mongo3`

The client containers install their own Python 3.12 and PyMongo 4.16.0, so the host's PyMongo
version does not affect the experiments.

## 1. Set up the MongoDB replica set

Run these from the repository root.

```bash
# Host Python environment (a conda environment with requirements.txt installed also works)
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# Start the three MongoDB containers
docker-compose -f compose.yaml up -d

# Initialize replica set rs0 (or check it if it already exists)
.venv/bin/python setup_majority.py
```

`setup_majority.py` creates rs0 with mongo1 at priority 2 and mongo2/mongo3 at priority 1. It then
waits until mongo1 is PRIMARY and the other two are SECONDARY. When it succeeds it prints the
roles, for example
`{"roles": {"mongo1": "PRIMARY", "mongo2": "SECONDARY", "mongo3": "SECONDARY"}, ...}`.

Make sure the active Docker context is the one running the containers (`docker context ls`).
If you use Colima with a profile named `consistency-lab`, the scripts pick it up automatically.
Otherwise they use your current context.

## 2. Set up each configuration's client

Each configuration has its own client container. Build and start it, then run its setup script.
The setup script adds the node tags used for routing (both configurations use the same tags) and
checks that the cluster is healthy.

```bash
# Configuration 1
docker-compose -f compose.yaml -f config1/compose.config1.yaml up -d --build client-config1
.venv/bin/python config1/setup_config1.py

# Configuration 2
docker-compose -f compose.yaml -f config2/compose.config2.yaml up -d --build client-config2
.venv/bin/python config2/setup_config2.py
```

Compose may warn about "orphan containers" when the other configuration's client is already
running. The warning is harmless.

## 3. Run the smoke tests

A smoke run uses 3 trials per model per phase. It checks that everything works end to end in about
a minute per configuration, and it does not overwrite the formal `*_results.json` files.
Run the scripts **from inside the configuration folder**, one at a time. The node-failure and
partition scripts stop or disconnect a MongoDB container and restore it afterwards.

```bash
cd config1
../.venv/bin/python normal_config1_experiment.py --smoke
../.venv/bin/python node_failure_config1_experiment.py --smoke
../.venv/bin/python network_partition_config1_experiment.py --smoke
cd ..

cd config2
../.venv/bin/python normal_config2_experiment.py --smoke
../.venv/bin/python node_failure_config2_experiment.py --smoke
../.venv/bin/python network_partition_config2_experiment.py --smoke
cd ..
```

Each run prints progress lines such as `normal RYW 3/3 {'no_violation_observed': 3}` and ends with
`RESULT_DIRECTORY=.../results_configN/<run-id>`.

## 4. Run the experiments

Each configuration has three scenarios. Run them one at a time, from inside the configuration
folder.

| Scenario | Entry point | What happens | Trials per model |
|---|---|---|---|
| Normal operation | `normal_configN_experiment.py` | All nodes healthy | 1,000 |
| Node failure | `node_failure_configN_experiment.py` | `docker stop mongo2`, test; restart mongo2, wait for recovery, test again | 500 during + 500 after |
| Network partition | `network_partition_configN_experiment.py` | Disconnect `mongo1` from the network, wait for a new primary, test; reconnect, wait for mongo1 to become primary again, test again | 60 during + 60 after |

That is 8,480 trials per configuration. The full Configuration 1 run took about 20 minutes on the
test machine, most of it in the node-failure scenario. Configuration 2 takes about 20–40 minutes,
depending on timeouts.

```bash
cd config1          # or config2, using the config2 file names
../.venv/bin/python normal_config1_experiment.py
../.venv/bin/python node_failure_config1_experiment.py
../.venv/bin/python network_partition_config1_experiment.py

# Audit a finished run (use the RESULT_DIRECTORY printed at the end of the run)
../.venv/bin/python audit_config1.py results_config1/<run-directory>
```

The optional standalone read-your-writes run is started the same way:
`../.venv/bin/python test_ryw_configN.py [--smoke]`.

### Outputs

Every run, smoke or formal, creates `results_configN/<timestamp>-<scenario>-<smoke|formal>-<id>/`
containing:

- `manifest.json`: settings, trial counts and source-file hashes
- `source/`: a snapshot of the code that ran
- `history.jsonl`: every trial with each operation's value, error, target node and timing
- `summary.json` / `summary.csv`: per-phase, per-model counts
- `mongo1.log`, `mongo2.log`, `mongo3.log`: database logs for the run
- `COMPLETE`: written when the run finished normally
- `audit.json`, `examples.json`: written by the audit script

A formal run also writes `normal_configN_results.json`, `node_failure_configN_results.json` or
`network_partition_configN_results.json` in the configuration folder.

Each trial is classified as one of:

- **no_violation_observed**: the check completed and the consistency property held
- **violation**: the check completed and the property was broken
- **unavailable**: a required operation failed, for example because its target node was down
- **inconclusive**: there was not enough evidence to decide, for example because the first read returned no document

The audit script fails with an assertion error if anything does not match. It checks the
configured concerns and sessions, which node served each operation, every classification, and the
recovery of the cluster.

## 5. Shut down

```bash
docker-compose -f compose.yaml -f config1/compose.config1.yaml -f config2/compose.config2.yaml stop client-config1 client-config2
docker-compose -f compose.yaml stop        # also stops mongo1–mongo3 (`down` removes them; rerun step 1 afterwards)
```

## Troubleshooting

- **`Start client-configN before running experiments`**: run step 2 for that configuration.
- **A run was interrupted**: the scripts restore the cluster in a `finally` block. After a hard
  kill, rerun `setup_configN.py`: it reconnects `mongo1` to the network if needed, starts any
  stopped node, and waits for mongo1 PRIMARY and mongo2/mongo3 SECONDARY.
- **`BlockingIOError` on start**: another run of the same configuration is still in progress (each
  configuration uses a lock file). Wait for it to finish.

## Results

- [`config1/config1_summary.md`](config1/config1_summary.md): Configuration 1 results
- [`config2/config2_summary.md`](config2/config2_summary.md): Configuration 2 results
- [`config2/configuration2_report.md`](config2/configuration2_report.md): the Configuration 2 report
