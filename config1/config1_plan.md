# Configuration 1: prior predictions and experimental plan

## Configuration

Application write concern w=1; read concern local; read preference secondary;
causal consistency OFF. Use one replica-set MongoClient and no explicit session:
every operation runs in its own implicit session and carries no afterClusterTime.
Node tags fix Secondary 1 to mongo2 and Secondary 2 to mongo3. Writes follow the primary.
No fallback is allowed when a tagged node is not a secondary. Diagnostic oplog queries
use separate direct clients and local reads, not the application read policy.
MongoDB version and replica configuration are recorded by setup_config1.py. The client
container uses Python 3.12 and PyMongo 4.16.0 on the existing project Docker network,
built from the same image definition as Configuration 2. Host-side launchers copy the
current Config 1 Python files into /lab with docker cp before starting each worker.

This replaces the earlier Configuration 1 setup, which ran on the host with three
independent direct connections (archived in archive_direct_connection/). The client,
connection, routing, test functions and scenario procedure are now identical to
Configuration 2; only the write concern, read concern and session settings differ.

## Predictions made before testing

With w=1 the primary acknowledges a write before any secondary has it; with read
concern local and no causal session, a secondary read returns whatever that node has
applied. Nothing ties a read to the client's earlier operations.

- Normal:
  - RYW: not guaranteed. Violations are expected when R1 on mongo2 runs before W1 has
    replicated.
  - MR: not guaranteed. A violation needs R1 on mongo2 to see W1 while R2 on mongo3 does
    not; this is possible but expected to be rare.
  - MW: expected to hold. Both writes go through one primary, whose oplog orders them,
    and secondaries apply the oplog in order.
  - WFR: expected to hold. A secondary only holds versions the primary already wrote,
    and a dependent write replicated to mongo2 arrives after the source version.
- Node failure: stop mongo2. w=1 writes still succeed on mongo1, but every model needs a
  read from tagged mongo2, so all four should be unavailable. After recovery, expect the
  normal pattern; RYW violations may be elevated while mongo2 catches up.
- Partition: disconnect mongo1, including its application connection. Wait for a new
  primary on the remaining side; w=1 writes should use it. If mongo2 is elected primary,
  all models lose their required tagged-secondary1 read. If mongo3 is elected primary,
  RYW/MW/WFR can use mongo2, with RYW violations expected as under normal operation,
  while MR cannot complete its second read on tagged mongo3. The partition phase has no
  baseline wait, so a secondary read may return no document at all: RYW counts this as a
  violation, while MR and WFR count it as inconclusive.
- Recovery: reconnect mongo1, wait for priority takeover and healthy roles. Read back
  a new majority-written barrier on all three nodes, then wait two seconds. RYW
  violations may be elevated immediately after recovery.

## Repetitions and preserved test structure

Normal: 1000 trials per model. Node failure: 500 per model during and 500 after.
Partition: 60 per model during and 60 after. Total 8480 formal trials.
A --smoke run uses 3 per model per phase; its results are excluded from formal totals.
Standalone test_ryw_config1.py is optional and not part of the 8480-case total.

The test functions, baseline waits, timeouts, retries and model order are the same as
Configuration 2. Normal selection and connection timeouts are 30s; fault/recovery
timeouts are 500ms. Read maxTimeMS=2s, socket timeout=4s. Automatic read/write retries
are OFF.

## Comparison with Configuration 2

Both configurations now use the same client container image, replica-set client,
tag-based routing, test functions and fault procedure. Differences in outcome between
the two can therefore be attributed to the concern and session settings rather than to
connection method. The two runs still happen at different times on the same shared
host, so timing-dependent rates are not exactly repeatable.

## Evidence and recovery

Each scenario has its own entry-point script and scenario configuration file. Shared
helpers implement logging, waits and recovery. Save source hashes before each run;
record operation values, errors, actual destinations and operationTime. The audit
checks that application writes use w=1, reads use read concern local without
afterClusterTime, destinations match the recorded roles, and classifications follow
from the recorded values. Use try/finally for fault recovery and a lock to prevent
concurrent Configuration 1 runs.

## Sources and AI usage

- https://www.mongodb.com/docs/manual/reference/write-concern/
- https://www.mongodb.com/docs/manual/reference/read-concern-local/
- https://www.mongodb.com/docs/manual/core/read-preference/
- https://www.mongodb.com/docs/manual/core/causal-consistency-read-write-concerns/

Claude Code (Anthropic) ported Configuration 1 onto the Configuration 2 harness and
wrote this plan. Observations must come from actual runs. Zero violations is not a
universal proof.
