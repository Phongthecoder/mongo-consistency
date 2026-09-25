# Configuration 2: prior predictions and experimental plan

## Configuration

Application write concern majority; read concern majority; read preference secondary;
causal consistency ON. Use one replica-set MongoClient and one explicit, sequential
causal session per trial. W1, R1/R2, W2 and dependent writes receive that same session.
Node tags fix Secondary 1 to mongo2 and Secondary 2 to mongo3. Writes follow the primary.
No fallback is allowed when a tagged node is not a secondary. Diagnostic oplog queries
use separate direct clients and local reads, not the application session or read policy.
MongoDB version and replica configuration are recorded by setup_config2.py. The client
container uses Python 3.12 and PyMongo 4.16.0 on the existing project Docker network. Host-side launchers copy the current Config 2
Python files into /lab with docker cp before starting each worker; no Desktop bind
mount is required. Source snapshots record the same input files.

## Predictions made before testing

All four properties are expected for completed operation sequences under documented
causal-session conditions. Failures can make an operation unavailable; errors do not
establish or refute a property whose required operation sequence did not complete.

- Normal: successful RYW/MR reads obey causal lower bounds; sequential MW and dependent
  WFR operations respect their recorded order/dependencies.
- Node failure: stop mongo2. Majority writes can proceed on mongo1+mongo3, but tests
  requiring a read from tagged mongo2 should be unavailable. After recovery, expect
  no stale successful reads or observed order/dependency violations.
- Partition: disconnect mongo1, including its application connection. Wait for a new
  primary on the majority side. Writes should use it. If mongo2 is elected primary,
  all models lose their required tagged-secondary1 read. If mongo3 is elected primary,
  RYW/MW/WFR can use mongo2, while MR cannot complete its second read on tagged mongo3.
  These are routing-related availability predictions, not consistency failures.
- Recovery: reconnect mongo1, wait for priority takeover and healthy roles. Read back
  a new majority-written barrier on all three nodes, then wait two seconds.

## Repetitions and preserved test structure

Normal: 1000 trials per model. Node failure: 500 per model during and 500 after.
Partition: 60 per model during and 60 after. Total 8480 formal trials.
A --smoke run uses 3 per model per phase; its results are excluded from formal totals.
Standalone test_ryw_config2.py is optional and not part of the 8480-case total.

Retain baseline -> W1 -> read structure, fixed read targets, original model order,
and original per-phase baseline waits. Each trial has unique IDs. Normal selection
and connection timeouts are 30s; fault/recovery timeouts are 500ms. Read maxTimeMS=2s,
write wtimeout=2s, socket timeout=4s. Automatic read/write retries are OFF.

MW: observe W2, perform ten more reads, inspect W1/W2 oplog identity and ordering on
secondary1; missing W2 evidence is inconclusive. WFR: check primary x, dependent y and
source x on secondary1, plus source-before-dependent oplog order. These are finite
checks, not proof over arbitrary concurrent executions or all replicas.

## Connection change and comparison limits

The original separate direct clients cannot share one ClientSession. A replica-set
client in the Docker network is necessary for correct session propagation and strict
secondary routing. This changes failover behavior: writes can reach a newly elected
primary, whereas the original fixed writer could not. The ON/OFF runs therefore are
not a controlled single-variable comparison. Report this explicitly.

## Evidence and recovery

Each scenario has its own entry-point script and scenario configuration file. Shared
helpers implement logging, waits and recovery. Save source hashes before each run;
record operation values, errors, actual destinations, LSIDs, afterClusterTime and
operationTime. Audit causal lower bounds, settings and classifications independently.
Use try/finally for fault recovery and a lock to prevent concurrent Configuration 2 runs.
Record stopped-container state; docker stop is not assumed to imply graceful shutdown.

## Sources and AI usage

- https://www.mongodb.com/docs/manual/core/causal-consistency-read-write-concerns/
- https://www.mongodb.com/docs/manual/core/read-preference/
- https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/transactions/

OpenAI Codex assists with implementation, execution, evidence checks and documentation.
Observations must come from actual runs. Zero violations is not a universal proof.
