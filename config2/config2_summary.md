# Configuration 2: Normal-Condition Consistency Experiments

## Configuration

Three MongoDB 8.3.11 containers form replica set rs0. mongo1 has priority 2; mongo2 and mongo3 have priority 1. The experiment client runs Python 3.12.14 and PyMongo 4.16.0 in a container on the same Docker network.

```text
Write concern:       majority
Read concern:        majority
Read preference:     secondary
Causal consistency:  ON
```

`config2.py` defines the configuration separately from the experiment scripts. One replica-set MongoClient creates one explicit causal session per trial. Every related application write and read receives that same session and executes sequentially. The tested secondary reads use strict secondary preference with node tags: Secondary 1 is mongo2 and Secondary 2 is mongo3. Writes follow the current primary. WFR also includes an explicitly identified primary-side dependency check. Read/write retries are disabled.

A causal session tracks preceding operation times. Subsequent reads carry afterClusterTime and cannot successfully return a snapshot older than the required bound. Under the documented majority read/write conditions, the expected guarantee covers RYW, MR, MW and WFR. A lagging or unavailable target may make an operation wait or fail instead.

## Predictions and experiments

### 1. Read-your-writes (RYW)

**Prediction:** a successful read after an acknowledged write in the same session should include that write.

**Experiment:** establish an old value on Secondary 1, write a new version through the primary, and read Secondary 1 in the same session. An older returned version is a violation.

### 2. Monotonic reads (MR)

**Prediction:** a later successful read in the session should not return an older version, even when reading a different secondary.

**Experiment:** establish a baseline on both secondaries, write a newer version, read Secondary 1, then read Secondary 2. Compare the returned versions and audit the second read's causal lower bound.

### 3. Monotonic writes (MW)

**Prediction:** sequential, acknowledged writes in the session should preserve their order.

**Experiment:** issue W1 and then W2. Observe W2 on Secondary 1, perform ten additional reads for regression, and inspect the replica's oplog entries for write identity and order. Unlike the original loop, this check does not stop immediately upon first seeing W2. Missing evidence within the bounded observation period is inconclusive.

### 4. Writes-follow-reads (WFR)

**Prediction:** a dependent write following a read in the session should respect that read's causal history.

**Experiment:** read version x, then write y containing based_on_version. Check primary x, wait for y on Secondary 1, inspect its x version, and check source-x before dependent-y in that replica's oplog. Oplog inspection is a separate diagnostic local read; it is not an application operation in the causal session.

## Experimental principle

Classify completed checks as no violation observed or violation. Operation errors are unavailable; insufficient evidence is inconclusive. Neither errors nor zero observed violations prove a general guarantee. Unique IDs and source snapshots prevent confusion with earlier trials. Timeout limits and try/finally recovery protect each fault experiment.

## Results (`normal_config2_experiment.py`, 1,000 trials per model)

| Model | Trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| Read-your-writes | 1000 | 1000 | 0 | 0 | 0 |
| Monotonic reads | 1000 | 1000 | 0 | 0 | 0 |
| Monotonic writes | 1000 | 1000 | 0 | 0 | 0 |
| Writes-follow-reads | 1000 | 1000 | 0 | 0 | 0 |

These figures describe only the completed normal-condition run. The prediction concerns successful operation sequences; finite observations test specific schedules rather than establish a mathematical proof.

---

# Configuration 2: Node-Failure Consistency Experiments

## Setup (`node_failure_config2.py` / `node_failure_config2_experiment.py`)

Stop mongo2 with docker stop. The primary and mongo3 remain available for majority writes, but strict secondary reads tagged for mongo2 have no eligible target. Each model runs 500 trials during the outage and 500 after recovery. Normal selection/connect timeouts are 30 seconds; fault/recovery settings are 500 milliseconds. Actual request duration can exceed those settings. Read maxTimeMS is 2 seconds, write wtimeout is 2 seconds, and socket timeout is 4 seconds.

Recovery starts the node, checks one primary and two secondaries, reads back a new majority-written barrier on all three nodes, and waits two seconds before measuring. Container state is logged; docker stop is not assumed to be a verified graceful shutdown.

## Predictions

- RYW cannot read its fixed tagged target while mongo2 is stopped.
- MR cannot complete its first read from mongo2.
- MW writes can succeed, but observing them on mongo2 is unavailable.
- WFR cannot complete its initial mongo2 read and dependent-write chain.
- After recovery, successful sequences should satisfy the causal consistency predicates.

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
| Read-your-writes | 500 | 500 | 0 | 0 | 0 |
| Monotonic reads | 500 | 500 | 0 | 0 | 0 |
| Monotonic writes | 500 | 500 | 0 | 0 | 0 |
| Writes-follow-reads | 500 | 500 | 0 | 0 | 0 |

Unavailable trials measure the missing read or observation path; they do not show that the entire replica set cannot accept writes. Their outcomes cannot be counted as either confirmed consistency violations or successful consistency checks.

---

# Configuration 2: Network-Partition Consistency Experiments

## Setup (`network_partition_config2.py` / `network_partition_config2_experiment.py`)

Disconnect mongo1 from the Docker network, cutting both replication traffic and client access to that node. Wait for a new primary on the remaining two-node majority. The replica-set client can use this new primary for writes. Each model runs 60 trials during the partition and 60 after reconnecting mongo1 and verifying its priority takeover, healthy roles and three-node read-back barrier.

The recorded roles at the formal partition start were: `{'mongo1': 'UNREACHABLE', 'mongo2': 'SECONDARY', 'mongo3': 'PRIMARY'}`.

Recorded acknowledged application writes during the partition: `{'baseline_write': 238, 'W1': 237, 'W2': 60, 'dependent_write': 60}`. Recorded write targets: `['mongo3']`.

## Predictions

Successful sequences should retain causal consistency. Availability depends on the election result and fixed secondary tags. If mongo2 becomes primary, the mongo2 secondary tag is ineligible for all models' required first/observation read. If mongo3 becomes primary, mongo2 can serve RYW/MW/WFR reads, but MR cannot complete its second read from mongo3. No fallback to a primary is allowed for these secondary reads. Transient driver/write errors are recorded separately from stale successful reads.

## Results (60 trials per model per phase)

### During partition

| Model | Trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| Read-your-writes | 60 | 57 | 0 | 3 | 0 |
| Monotonic reads | 60 | 0 | 0 | 60 | 0 |
| Monotonic writes | 60 | 60 | 0 | 0 | 0 |
| Writes-follow-reads | 60 | 60 | 0 | 0 | 0 |

### After recovery

| Model | Trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| Read-your-writes | 60 | 60 | 0 | 0 | 0 |
| Monotonic reads | 60 | 60 | 0 | 0 | 0 |
| Monotonic writes | 60 | 60 | 0 | 0 | 0 |
| Writes-follow-reads | 60 | 60 | 0 | 0 | 0 |

In this run, mongo3 became primary and mongo2 remained secondary. RYW completed 57 of 60 trials; three trials encountered majority write timeouts (two at the baseline write and one at W1). MW and WFR each completed all 60 trials without an observed violation. All 60 MR trials could read mongo2 but could not perform R2 on mongo3 because it was now primary. After reconnection, all 240 trials completed without an observed violation.

This client can send writes to a newly elected primary. A read still fails when its required tag identifies a primary rather than an eligible secondary. These results must therefore be interpreted with the recorded roles and failing operation stages. Configuration 1 now uses the same client and routing, so availability differences between the two runs also depend on which node was elected in each run.

---

# Cross-scenario comparison

| Phase | Total trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| normal | 4000 | 4000 | 0 | 0 | 0 |
| node_during | 2000 | 0 | 0 | 2000 | 0 |
| node_after | 2000 | 2000 | 0 | 0 | 0 |
| partition_during | 240 | 177 | 0 | 63 | 0 |
| partition_after | 240 | 240 | 0 | 0 | 0 |

Across **8,480 formal trials**, there were **6417 with no observed violation, 0 violations, 2063 unavailable and 0 inconclusive**. The 60-case preflight and optional standalone RYW entry point are excluded.

| Model | Normal | Node failure (during / after) | Partition (during / after) |
|---|---:|---:|---:|
| Read-your-writes | 0.00% | 100% unavail / 0.00% | 0.00%, 5.00% unavail / 0.00% |
| Monotonic reads | 0.00% | 100% unavail / 0.00% | 100% unavail / 0.00% |
| Monotonic writes | 0.00% | 100% unavail / 0.00% | 0.00% / 0.00% |
| Writes-follow-reads | 0.00% | 100% unavail / 0.00% | 0.00% / 0.00% |

Percentages are violation rates except where marked "unavail", which is the unavailability rate during the fault window.

The observations agree with the prediction for the tested schedules: no completed check violated its consistency predicate. The results should be read against the conditional prediction: completed operations should preserve causal order, while unavailable targets may prevent completion. No observed violation is supporting evidence for the sampled schedules, not a universal proof. Errors are not stale successful results.

## Audit and limitations

The independent audits checked 8480 trial classifications and 35097 application reads with causal lower bounds. They verified majority concerns, strict secondary wire preference and tags, actual node roles/destinations, matching session IDs, source hashes, and 8 three-node recovery barriers. All three runs ended with mongo1 PRIMARY and mongo2/mongo3 SECONDARY.

- All nodes and the client share one host/VM. There is no concurrent application workload or forced replication delay; the earlier lab also remains running in that VM.
- Faults occur before each phase. This does not exhaust all possible mid-session failure timings.
- MW and WFR use finite observation windows and diagnostic evidence from one secondary.
- Configuration 1 (OFF) now uses the same client container, replica-set client, routing, test functions and fault procedure, so the comparison differs only in concern and session settings. The two configurations were still run at different times on a shared host, so timing-dependent rates are not exactly repeatable. (An earlier Configuration 1 run used independent direct clients on the host; it is archived in `config1/archive_direct_connection/`.)
- Fault/recovery trials use short timeouts. Write errors may leave an unknown outcome; they are never treated as proof that no write occurred.

## Files and reproduction

Configuration: config2.py. Four test functions: normal_config2_experiment.py. Each fault has its own configuration and experiment entry point. config2_helpers.py provides shared logging, worker communication, waits, phase execution and recovery. Source is copied to the client container before execution; Desktop bind mounting is not required.

```bash
docker-compose -f compose.yaml -f config2/compose.config2.yaml up -d --build client-config2
.venv/bin/python config2/setup_config2.py
cd config2
../.venv/bin/python normal_config2_experiment.py
../.venv/bin/python node_failure_config2_experiment.py
../.venv/bin/python network_partition_config2_experiment.py
../.venv/bin/python audit_config2.py results_config2/<run-directory>
```

These commands assume the existing rs0 is already initialized. For a fresh project deployment, start the base compose services and run the existing setup_majority.py bootstrap before configuring Config 2 tags.

The host requires PyMongo (`.venv/bin/python -m pip install -r requirements.txt`). See [README_CONFIG2.md](README_CONFIG2.md) for Docker context details. Each scenario accepts --smoke. Run scenarios sequentially.

Formal evidence directories:

- normal: `results_config2/20260923T083607Z-normal-formal-7d0a6c`
- node: `results_config2/20260923T083624Z-node-formal-6164b0`
- partition: `results_config2/20260923T090231Z-partition-formal-fae952`

Each directory contains the manifest, source snapshots, history.jsonl, CSV/JSON summaries, audit.json, representative examples and database logs. Root-level normal_config2_results.json, node_failure_config2_results.json and network_partition_config2_results.json point to their formal run directories.

## References and AI usage

- [MongoDB: Causal Consistency and Read and Write Concerns](https://www.mongodb.com/docs/manual/core/causal-consistency-read-write-concerns/)
- [MongoDB: Read Preference](https://www.mongodb.com/docs/manual/core/read-preference/)
- [MongoDB: Write Concern](https://www.mongodb.com/docs/manual/reference/write-concern/)

