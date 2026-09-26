# Configuration 1: Normal-Condition Consistency Experiments

## Configuration

Three MongoDB 8.3.11 containers form replica set rs0. mongo1 has priority 2; mongo2 and mongo3 have priority 1. The experiment client runs Python 3.12.14 and PyMongo 4.16.0 in a container on the same Docker network.

```text
Write concern:       w = 1
Read concern:        local
Read preference:     secondary
Causal consistency:  OFF
```

`config1.py` defines the configuration separately from the experiment scripts. One replica-set MongoClient is used with no explicit session: every operation runs in its own implicit session and carries no afterClusterTime. The tested secondary reads use strict secondary preference with node tags: Secondary 1 is mongo2 and Secondary 2 is mongo3. Writes follow the current primary. WFR also includes an explicitly identified primary-side dependency check. Read/write retries are disabled.

The client, connection, routing, test functions and fault procedure are identical to Configuration 2; only the write concern, read concern and session settings differ. With w=1 the primary acknowledges a write before any secondary has it. With read concern local and no causal session, a secondary read returns whatever that node has applied, and nothing ties it to the client's earlier operations.

## Predictions and experiments

Predictions were recorded in [config1_plan.md](config1_plan.md) before the formal runs.

### 1. Read-your-writes (RYW)

Prediction: not guaranteed. Violations are expected when R1 on mongo2 runs before W1 has replicated.

Experiment: write a baseline and wait until mongo2 has it; write W1 through the primary; immediately read x from mongo2 (R1). A violation is a read that returns a version older than W1, or no document.

### 2. Monotonic reads (MR)

Prediction: not guaranteed, but violations are expected to be rare. A violation needs R1 on mongo2 to see W1 while R2 on mongo3 does not.

Experiment: write a baseline and wait until both secondaries have it; write W1; read x from mongo2 (R1) and then from mongo3 (R2). A violation is R2 returning an older version than R1.

### 3. Monotonic writes (MW)

Prediction: expected to hold. Both writes go through one primary, whose oplog orders them, and secondaries apply the oplog in order.

Experiment: after W1, write W2; wait up to one second to observe W2 on mongo2, then read ten more times. A violation is any later read older than W2, or W1/W2 oplog entries on mongo2 in the wrong order.

### 4. Writes-follow-reads (WFR)

Prediction: expected to hold. A secondary only holds versions the primary already wrote, and a dependent write replicated to mongo2 arrives after its source version.

Experiment: read x from mongo2 (R1); write a dependent document y recording the version read; check that the primary's x is at least that version; wait for y on mongo2 and check mongo2's x is at least that version; check the source and dependent oplog entries are in order.

## Experimental principle

Classify completed checks as no violation observed or violation. Operation errors are unavailable; insufficient evidence is inconclusive. Neither errors nor zero observed violations prove a general guarantee. Unique IDs and source snapshots prevent confusion with earlier trials. Timeout limits and try/finally recovery protect each fault experiment.

## Results (`normal_config1_experiment.py`, 1,000 trials per model)

| Model | Trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| Read-your-writes | 1000 | 2 | 998 | 0 | 0 |
| Monotonic reads | 1000 | 998 | 2 | 0 | 0 |
| Monotonic writes | 1000 | 1000 | 0 | 0 | 0 |
| Writes-follow-reads | 1000 | 1000 | 0 | 0 | 0 |

All four results agree with the predictions. In all 998 RYW violations, R1 returned the trial's baseline version, the value immediately before W1. Median round-trip times inside the Docker network were about 0.12 ms for W1 and 0.13 ms for R1, so the read reached mongo2 before the w=1 write had replicated there in almost every trial. MR violated twice: R1 on mongo2 saw W1 and R2 on mongo3 did not. MW and WFR held in every trial.

---

# Configuration 1: Node-Failure Consistency Experiments

## Setup (`node_failure_config1.py` / `node_failure_config1_experiment.py`)

Stop mongo2 with docker stop. The primary remains available for w=1 writes, but strict secondary reads tagged for mongo2 have no eligible target. Each model runs 500 trials during the outage and 500 after recovery. Normal selection/connect timeouts are 30 seconds; fault/recovery settings are 500 milliseconds. Read maxTimeMS is 2 seconds and socket timeout is 4 seconds.

Recovery starts the node, checks one primary and two secondaries, reads back a new majority-written barrier on all three nodes, and waits two seconds before measuring. Container state is logged; docker stop is not assumed to be a verified graceful shutdown.

## Predictions

- RYW cannot read its fixed tagged target while mongo2 is stopped.
- MR cannot complete its first read from mongo2.
- MW writes can succeed, but observing them on mongo2 is unavailable.
- WFR cannot complete its initial mongo2 read.
- After recovery, expect the normal pattern; RYW violations may be elevated while mongo2 catches up.

## Results (500 trials per model per phase)

### During failure

| Model | Trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| Read-your-writes | 500 | 0 | 0 | 500 | 0 |
| Monotonic reads | 500 | 0 | 0 | 500 | 0 |
| Monotonic writes | 500 | 0 | 0 | 500 | 0 |
| Writes-follow-reads | 500 | 0 | 0 | 500 | 0 |

### After recovery

| Model | Trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| Read-your-writes | 500 | 50 | 450 | 0 | 0 |
| Monotonic reads | 500 | 500 | 0 | 0 | 0 |
| Monotonic writes | 500 | 500 | 0 | 0 | 0 |
| Writes-follow-reads | 500 | 385 | 0 | 0 | 115 |

During the outage every trial failed at its mongo2 read (R1 for RYW, MR and WFR; observe_W2 for MW) with ServerSelectionTimeoutError, as predicted. Unavailable trials measure the missing read or observation path; they do not show that the replica set could not accept writes.

After recovery, the node-failure phases (unlike the normal phase) do not wait for the baseline to reach mongo2 before W1. Of the 450 RYW violations, 335 read the baseline version and 115 read no document at all, meaning even the trial's baseline write had not yet reached mongo2. The same situation made 115 WFR trials inconclusive: R1 returned no document, so there was no dependency version to check. RYW violated 90.00% of trials, slightly below the normal-condition rate (99.80%); the rates are not directly comparable because the normal phase waits for the baseline first. MR, MW and every completed WFR check held.

---

# Configuration 1: Network-Partition Consistency Experiments

## Setup (`network_partition_config1.py` / `network_partition_config1_experiment.py`)

Disconnect mongo1 from the Docker network, cutting both replication traffic and client access to that node. Wait for a new primary on the remaining two-node majority. The replica-set client can use this new primary for writes. Each model runs 60 trials during the partition and 60 after reconnecting mongo1 and verifying its priority takeover, healthy roles and three-node read-back barrier.

The recorded roles at the formal partition start were: `{'mongo1': 'UNREACHABLE', 'mongo2': 'SECONDARY', 'mongo3': 'PRIMARY'}`.

Recorded acknowledged application writes during the partition: `{'baseline_write': 240, 'W1': 240, 'W2': 60, 'dependent_write': 53}`. Recorded write targets: `['mongo3']`.

## Predictions

Availability depends on the election result and fixed secondary tags. If mongo2 becomes primary, the mongo2 secondary tag is ineligible for all models' required first/observation read. If mongo3 becomes primary, mongo2 can serve RYW/MW/WFR reads, with RYW violations expected as under normal operation, while MR cannot complete its second read from mongo3. The partition phase has no baseline wait, so a secondary read may return no document: RYW counts this as a violation, while MR and WFR count it as inconclusive.

## Results (60 trials per model per phase)

### During partition

| Model | Trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| Read-your-writes | 60 | 0 | 60 | 0 | 0 |
| Monotonic reads | 60 | 0 | 0 | 60 | 0 |
| Monotonic writes | 60 | 60 | 0 | 0 | 0 |
| Writes-follow-reads | 60 | 53 | 0 | 0 | 7 |

### After recovery

| Model | Trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| Read-your-writes | 60 | 1 | 59 | 0 | 0 |
| Monotonic reads | 60 | 2 | 0 | 0 | 58 |
| Monotonic writes | 60 | 60 | 0 | 0 | 0 |
| Writes-follow-reads | 60 | 3 | 0 | 0 | 57 |

In this run, mongo3 became primary and mongo2 remained secondary, and all application writes went to mongo3. RYW completed every trial and violated all 60: 57 reads returned the baseline version and 3 returned no document. All 60 MR trials could read mongo2 but could not perform R2 on mongo3 because it was now primary. MW completed all 60 trials without an observed violation. WFR completed 53 without an observed violation; in the other 7, R1 returned no document.

After reconnection, RYW violated 59 of 60 trials; 58 of those reads returned no document, so mongo2 was still behind even the trial's baseline write. The same lag made 58 MR and 57 WFR trials inconclusive. MW held in all 60 trials, and every completed MR and WFR check held.

---

# Cross-scenario comparison

| Phase | Total trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| normal | 4000 | 3000 | 1000 | 0 | 0 |
| node_during | 2000 | 0 | 0 | 2000 | 0 |
| node_after | 2000 | 1435 | 450 | 0 | 115 |
| partition_during | 240 | 113 | 60 | 60 | 7 |
| partition_after | 240 | 66 | 59 | 0 | 115 |

Across **8,480 formal trials**, there were **4614 with no observed violation, 1569 violations, 2060 unavailable and 237 inconclusive**. The 60-case preflight and optional standalone RYW entry point are excluded.

| Model | Normal | Node failure (during / after) | Partition (during / after) |
|---|---:|---:|---:|
| Read-your-writes | 99.80% | 100% unavail / 90.00% | 100.00% / 98.33% |
| Monotonic reads | 0.20% | 100% unavail / 0.00% | 100% unavail / 0.00% (96.67% inconcl) |
| Monotonic writes | 0.00% | 100% unavail / 0.00% | 0.00% / 0.00% |
| Writes-follow-reads | 0.00% | 100% unavail / 0.00% (23.00% inconcl) | 0.00% (11.67% inconcl) / 0.00% (95.00% inconcl) |

Percentages are violation rates except where marked "unavail" (unavailability rate during the fault window) or "inconcl" (inconclusive rate).

The observations agree with the predictions. RYW is violated in almost every trial in every phase where the read can complete, and MR was violated twice under normal operation. MW and WFR were never violated: every completed check found the writes and dependencies in order. Unavailability followed the fixed secondary tags exactly as predicted for the election result. No observed violation is supporting evidence for the sampled schedules, not a universal proof.

The earlier direct-connection version of Configuration 1 (archived in `archive_direct_connection/`) recorded a normal-condition RYW violation rate of 29.10% and 100% unavailability during the partition. The differences come from the connection method: the earlier host client reached each node through Docker's published ports, which is slower than container-to-container traffic and gave replication more time before the read; and its writes were pinned to mongo1, so it could not use the newly elected primary.

## Audit and limitations

The independent audits checked 8480 trial classifications and 41662 application reads. They verified w=1 writes to the recorded primary, read concern local with no afterClusterTime on every read, strict secondary wire preference and tags, actual node roles/destinations, no explicit session in any trial, source hashes, and 8 three-node recovery barriers. All three runs ended with mongo1 PRIMARY and mongo2/mongo3 SECONDARY.

- All nodes and the client share one host/VM. There is no concurrent application workload or forced replication delay.
- Faults occur before each phase. This does not exhaust all possible mid-session failure timings.
- MW and WFR use finite observation windows and diagnostic evidence from one secondary.
- Only the normal phase waits for the baseline to reach mongo2 before W1, so RYW rates in the fault phases are not directly comparable with the normal rate. Reads that return no document make MR and WFR trials inconclusive rather than tested.
- Configuration 1 and Configuration 2 now use the same client, connection and test procedure, but were run at different times on a shared host, so timing-dependent rates are not exactly repeatable.
- Fault/recovery trials use short timeouts. Write errors may leave an unknown outcome; they are never treated as proof that no write occurred.

## Files and reproduction

Configuration: config1.py. Four test functions: normal_config1_experiment.py. Each fault has its own configuration and experiment entry point. config1_helpers.py provides shared logging, worker communication, waits, phase execution and recovery. Source is copied to the client container before execution; Desktop bind mounting is not required.

```bash
docker-compose -f compose.yaml -f config1/compose.config1.yaml up -d --build client-config1
.venv/bin/python config1/setup_config1.py
cd config1
../.venv/bin/python normal_config1_experiment.py
../.venv/bin/python node_failure_config1_experiment.py
../.venv/bin/python network_partition_config1_experiment.py
../.venv/bin/python audit_config1.py results_config1/<run-directory>
```

These commands assume the existing rs0 is already initialized. For a fresh project deployment, start the base compose services and run the existing setup_majority.py bootstrap before configuring Config 1 tags.

The host requires PyMongo (`.venv/bin/python -m pip install -r requirements.txt`). See [README_CONFIG1.md](README_CONFIG1.md) for details. Each scenario accepts --smoke. Run scenarios sequentially.

Formal evidence directories:

- normal: `results_config1/20260926T025809Z-normal-formal-bd7852`
- node: `results_config1/20260926T025828Z-node-formal-1cfbf0`
- partition: `results_config1/20260926T031551Z-partition-formal-6c31ab`

Each directory contains the manifest, source snapshots, history.jsonl, CSV/JSON summaries, audit.json, representative examples and database logs. Root-level normal_config1_results.json, node_failure_config1_results.json and network_partition_config1_results.json point to their formal run directories.

## References and AI usage

- [MongoDB: Write Concern](https://www.mongodb.com/docs/manual/reference/write-concern/)
- [MongoDB: Read Concern "local"](https://www.mongodb.com/docs/manual/reference/read-concern-local/)
- [MongoDB: Read Preference](https://www.mongodb.com/docs/manual/core/read-preference/)
- [MongoDB: Causal Consistency and Read and Write Concerns](https://www.mongodb.com/docs/manual/core/causal-consistency-read-write-concerns/)

Claude Code (Anthropic) ported Configuration 1 onto the Configuration 2 harness, ran the experiments and wrote this summary from the recorded run directories and audits.
