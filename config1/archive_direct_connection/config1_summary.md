# Configuration 1: Normal-Condition Consistency Experiments

## Configuration

A three-node MongoDB replica set is used: one preferred primary (mongo1, priority 2) and two secondaries (mongo2 and mongo3, priority 1). The experiment scripts run on the host and connect directly to each node through its published port. The experiments in this section keep the database under normal operating conditions: no node failures or artificial network partitions.

```text
Write concern:       w = 1
Read concern:        local
Read preference:     secondary
Causal consistency:  OFF
```

`config1.py` defines the configuration separately from the experiment scripts. Writes are sent to the primary through a direct connection to mongo1. Reads are performed on secondaries through direct connections: Secondary 1 is mongo2 (port 27018) and Secondary 2 is mongo3 (port 27019). No causally consistent session is used.

With w=1, a write can be acknowledged once it is accepted by the primary, without waiting for the secondaries. With local, a secondary may return its current local state.

## Predictions and experiments

### 1. Read-your-writes (RYW)

Prediction: Not guaranteed.

After the client writes a new value, w=1 allows the primary to acknowledge the write before it has reached a secondary. An immediate local read from that secondary may therefore return the old value.

Experiment: Establish a known old value on the secondary, write a new value to the primary, and immediately read from the secondary. Repeat over many trials and count cases where the read returns the old rather than the newly written value.

### 2. Monotonic reads (MR)

Prediction: Not guaranteed.

Reads may be served by different secondaries, and the secondaries may be at different replication states. Without causal consistency, a client that first reads a newer version from one secondary may subsequently read an older version from another.

Experiment: Establish a baseline on both secondaries, write a newer version to the primary, then perform successive reads from Secondary 1 and Secondary 2. Compare version numbers and record a violation whenever the second read is older than the first.

### 3. Monotonic writes (MW)

Prediction: Expected to hold under normal operation.

Unlike reads, the client's writes are directed to the same primary. Sequential writes from the client are therefore processed through the primary in client order. The second write is issued only after the first write has been acknowledged.

Experiment: Issue two successive writes, W(x,a) followed by W(x,b), waiting for the first acknowledgement before issuing the second. Observe replication on a secondary for up to one second and check whether the later write is ever observed before, and then followed by, the earlier write.

### 4. Writes-follow-reads (WFR)

Prediction: Expected to hold under normal operation.

A secondary normally obtains its versions through replication from the primary. Therefore, if a client has read version v from a secondary, the primary that receives its subsequent write should normally already contain version v or a newer version.

Experiment: Store explicit version numbers. Read a version of x from a secondary and then perform a subsequent write through the primary. Inspect the primary's version of x and check whether it is at least as recent as the version previously observed by the client.

## Experimental principle

These experiments test Configuration 1 under normal conditions only. Node failures and network partitions are separate experimental conditions and are not introduced here. Observing a violation is evidence that a consistency property is not guaranteed; observing no violations in a finite number of trials does not by itself prove a guarantee. In the fault scenarios, an operation error is classified as unavailable rather than as a violation. Configuration 1 has no inconclusive category, so that column is shown as "–".

## Results (`normal_config1_experiment.py`, 1,000 trials per model)

| Model | Trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| Read-your-writes | 1000 | 709 | 291 | 0 | – |
| Monotonic reads | 1000 | 999 | 1 | 0 | – |
| Monotonic writes | 1000 | 1000 | 0 | 0 | – |
| Writes-follow-reads | 1000 | 1000 | 0 | 0 | – |

All four results agree with the predictions. The normal-condition script does not catch operation errors, so any error would have stopped the run; the recorded run completed every trial.

RYW violates on nearly a third of trials (29.10%): replication from mongo1 to Secondary 1 is fast (sub-millisecond, everything on one Docker host) but not instantaneous, and w=1 acknowledges the write before it has necessarily reached the secondary, so a substantial fraction of immediate reads still observe the old value. Monotonic reads is "not guaranteed" in principle, but because both secondaries pull from the same primary oplog and there is no artificial lag between them, divergence between two secondaries at read time is rare in practice: one violation in 1000 trials (0.10%). Monotonic writes and writes-follow-reads hold exactly as predicted, since both properties are enforced by routing every write through the same primary.

---

# Configuration 1: Node-Failure Consistency Experiments

## Setup (`node_failure_config1.py` / `node_failure_config1_experiment.py`)

The fault target is Secondary 1 (container `mongo2`, host port 27018), the node all four experiments above read from at least once. `docker stop mongo2` kills the mongod process while leaving the container and its data directory intact, so the client's TCP connect is refused almost immediately (fast failure), unlike the blackhole behaviour used for the network-partition scenario below.

Because config1.py's clients default to PyMongo's 30s server-selection timeout, this experiment uses its own clients with the server-selection and connect timeouts shortened to 500ms so that hundreds of trials against a dead node finish quickly; this is the only deviation from Configuration 1's tunables. Each of the four tests is run twice: once with mongo2 down (500 trials per model), and again after it is restarted, has rejoined as a healthy secondary, and a further two seconds have passed (500 trials per model).

## Predictions

- RYW: reads are pinned to Secondary 1 via `directConnection=True`, so PyMongo does not fail over to Secondary 2. The client should see 100% unavailability while the node is down, not stale reads.
- MR: the first read (Secondary 1) should be 100% unavailable during the outage, making the test as a whole unavailable rather than violated.
- MW: writes only ever touch the primary, so they are unaffected by a secondary's failure; the observation step (polling Secondary 1) becomes unavailable instead of violated.
- WFR: the write path (primary) is healthy, but the read step is 100% unavailable while Secondary 1 is down.
- After mongo2 restarts and catches up, all four properties should return to behaving as in the normal-condition experiment above.

## Results (500 trials per model per phase)

### During failure

| Model | Trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| Read-your-writes | 500 | 0 | 0 | 500 | – |
| Monotonic reads | 500 | 0 | 0 | 500 | – |
| Monotonic writes | 500 | 0 | 0 | 500 | – |
| Writes-follow-reads | 500 | 0 | 0 | 500 | – |

### After recovery

| Model | Trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| Read-your-writes | 500 | 243 | 257 | 0 | – |
| Monotonic reads | 500 | 500 | 0 | 0 | – |
| Monotonic writes | 500 | 500 | 0 | 0 | – |
| Writes-follow-reads | 500 | 500 | 0 | 0 | – |

All four during-failure predictions were confirmed: with a fixed direct connection to a specific node, a node failure is purely an availability fault, not a consistency fault. Every trial against the dead node was classified "unavailable" rather than producing a false satisfied or violated result. This matches the CAP-theorem framing: Configuration 1 sacrifices availability of that one access path rather than serving a stale read from elsewhere.

The after-recovery RYW violation rate (51.40%) is notably higher than the normal-condition baseline (29.10%). This was not predicted, but is explainable: immediately after mongo2 restarts it has to work through the oplog backlog accumulated during the outage before replication lag returns to steady state, so RYW reads immediately following recovery are more likely to catch a stale value than under long-run normal operation. Monotonic reads, monotonic writes, and writes-follow-reads all return to holding exactly as in the normal baseline once the node is healthy again.

---

# Configuration 1: Network-Partition Consistency Experiments

## Setup (`network_partition_config1.py` / `network_partition_config1_experiment.py`)

The fault target is the primary (container `mongo1`, host port 27017), disconnected with `docker network disconnect` from the Docker network that carries inter-node replication and heartbeat traffic. Unlike the node-failure scenario, the mongod process keeps running and its data is untouched; packets to and from it are silently dropped. This was verified empirically to behave differently from a stopped container: operations against a disconnected node hang until the client-side timeout expires (blackhole) rather than failing instantly with connection-refused. The same 500ms timeout override used for the node-failure scenario is applied here for the same reason.

Because mongo1 is configured with replica-set priority 2 against 1 for the other two members, it automatically reclaims PRIMARY once the partition heals, without any manual reconfiguration; this was confirmed to take up to somewhat over a minute in practice. Each of the four tests is run twice: once with mongo1 partitioned (60 trials per model, kept smaller than the other experiments because every failed attempt costs a full 500ms timeout), and again after the partition heals, mongo1 has reclaimed PRIMARY, and a further two seconds have passed (60 trials per model).

## Predictions

- All four models: Configuration 1 pins every write to a single fixed primary connection (`directConnection=True` to mongo1) with no automatic failover to whichever node the replica set elects next. When mongo1 is partitioned, the very first write of every trial should fail, making all four properties uniformly 100% unavailable rather than violated. The partition should look like a total write outage, not a staleness problem, exactly as with node failure. Reads to the two secondaries should remain largely unaffected, though they are not exercised in isolation here since every trial starts with a write.
- The remaining two members (mongo2, mongo3) should hold a new election and pick a primary among themselves within the ~10s default election timeout.
- After the partition heals, mongo1 should reclaim PRIMARY via priority takeover and behaviour should return to matching the normal-condition baseline.

## Results (60 trials per model per phase)

### During partition

| Model | Trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| Read-your-writes | 60 | 0 | 0 | 60 | – |
| Monotonic reads | 60 | 0 | 0 | 60 | – |
| Monotonic writes | 60 | 0 | 0 | 60 | – |
| Writes-follow-reads | 60 | 0 | 0 | 60 | – |

### After recovery

| Model | Trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| Read-your-writes | 60 | 1 | 59 | 0 | – |
| Monotonic reads | 60 | 59 | 1 | 0 | – |
| Monotonic writes | 60 | 60 | 0 | 0 | – |
| Writes-follow-reads | 60 | 60 | 0 | 0 | – |

In this run, mongo2 was elected primary during the partition. The during-partition prediction was confirmed exactly: with the primary unreachable and no failover in the client, every trial across all four models was unavailable rather than violated, and a new primary was elected among the remaining two members within the expected window.

The after-recovery prediction was only partially confirmed. Monotonic writes and writes-follow-reads returned to holding perfectly, as expected. Monotonic reads returned to a violation rate (1.67%) comparable to the normal baseline. Read-your-writes, however, spiked to 98.33% violated, far higher than both the normal baseline (29.10%) and the node-failure recovery spike (51.40%). This is explained by the amount of role churn involved: healing the partition forces mongo1 to catch up as a secondary, then trigger a priority-takeover election, flipping mongo1 secondary-to-primary and mongo2 primary-to-secondary in quick succession. Both transitions appear to leave replication measurably behind immediately afterward, so almost every read taken right after recovery caught a stale value on Secondary 1.

---

# Cross-scenario comparison

| Phase | Total trials | No violation observed | Violated | Unavailable | Inconclusive |
|---|---:|---:|---:|---:|---:|
| normal | 4000 | 3708 | 292 | 0 | – |
| node_during | 2000 | 0 | 0 | 2000 | – |
| node_after | 2000 | 1743 | 257 | 0 | – |
| partition_during | 240 | 0 | 0 | 240 | – |
| partition_after | 240 | 180 | 60 | 0 | – |

Across **8,480 formal trials**, there were **5631 with no observed violation, 609 violations and 2240 unavailable**. The optional standalone RYW entry point is excluded.

| Model | Normal | Node failure (during / after) | Partition (during / after) |
|---|---:|---:|---:|
| Read-your-writes | 29.10% | 100% unavail / 51.40% | 100% unavail / 98.33% |
| Monotonic reads | 0.10% | 100% unavail / 0.00% | 100% unavail / 1.67% |
| Monotonic writes | 0.00% | 100% unavail / 0.00% | 100% unavail / 0.00% |
| Writes-follow-reads | 0.00% | 100% unavail / 0.00% | 100% unavail / 0.00% |

Percentages are violation rates except where marked "unavail", which is the unavailability rate during the fault window.

The clearest pattern across both fault conditions is that monotonic writes and writes-follow-reads are robust: they depend only on all writes going through the same primary connection, which either works or is unavailable, never inconsistent. Read-your-writes is the most fragile property in this configuration under any kind of fault, and both fault types make it measurably worse than normal operation immediately after recovery, since recovery-time replication catch-up adds to the ordinary w=1 replication lag that already causes RYW violations under normal conditions.

## Audit and limitations

Configuration 1 has no independent audit script. The scripts record only per-model counts, not per-operation histories, so individual classifications cannot be re-checked after the run.

- All nodes and the client share one host. There is no concurrent application workload or forced replication delay.
- Faults occur before each phase. This does not exhaust all possible mid-session failure timings.
- MW uses a one-second observation window on one secondary; WFR checks only the primary's version of x.
- The after-recovery trials start two seconds after recovery is detected. This is not long enough for replication to settle after the partition's two role changes; a longer cool-down would likely show the RYW violation rate decaying back toward the normal-condition baseline.
- The OFF setup uses independent direct clients on the host; the Configuration 2 (ON) setup uses a shared replica-set client inside Docker. Routing, failover, Python runtime and network timing differ, so the two are not a controlled single-variable comparison.
- Fault/recovery trials use short 500ms timeouts. A timed-out write may still have been applied; it is counted as unavailable, never as proof that no write occurred.

## Files and reproduction

Configuration: config1.py. Four test functions: normal_config1_experiment.py. Each fault has its own configuration (node_failure_config1.py, network_partition_config1.py) and experiment entry point (node_failure_config1_experiment.py, network_partition_config1_experiment.py). The scripts run on the host; see [README_CONFIG1.md](README_CONFIG1.md).

```bash
docker-compose -f compose.yaml up -d
.venv/bin/python setup_majority.py
cd config1
../.venv/bin/python normal_config1_experiment.py
../.venv/bin/python node_failure_config1_experiment.py
../.venv/bin/python network_partition_config1_experiment.py
```

The host requires PyMongo (`.venv/bin/python -m pip install -r requirements.txt`). Each scenario accepts --smoke. Run scenarios sequentially.

Formal results:

- normal: `normal_config1_results.json`
- node: `node_failure_config1_results.json`
- partition: `network_partition_config1_results.json`

## References and AI usage

- [MongoDB: Write Concern](https://www.mongodb.com/docs/manual/reference/write-concern/)
- [MongoDB: Read Concern "local"](https://www.mongodb.com/docs/manual/reference/read-concern-local/)
- [MongoDB: Read Preference](https://www.mongodb.com/docs/manual/core/read-preference/)
- [MongoDB: Replica Set Elections](https://www.mongodb.com/docs/manual/core/replica-set-elections/)

AI usage: TODO (Configuration 1 author) — state what AI assistance, if any, was used for the original scripts and write-up. Claude Code (Anthropic) was used to restructure this document to match the Configuration 2 layout and to add the `--smoke` option; no results were changed.
