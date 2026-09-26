import subprocess
import time

from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern
from pymongo.read_preferences import Secondary


# ============================================================
# CONFIGURATION 1 -- NETWORK PARTITION fault
# ============================================================
# Same tunables as config1.py:
#   Write concern:       w = 1
#   Read concern:        local
#   Read preference:     secondary
#   Causal consistency:  OFF
#
# The fault target is the PRIMARY (container "mongo1", host
# port 27017), disconnected from the Docker network that
# carries replication/heartbeat traffic between the three
# mongod processes. Unlike node_failure_config1.py (which
# stops the process), the mongod keeps running and its data is
# untouched -- packets to/from it are just dropped, so it
# behaves like a real network partition rather than a crash:
#
#   - other members stop hearing heartbeats from it and, since
#     it also cannot reach a majority, MongoDB steps it down
#     from PRIMARY and holds a new election among the
#     remaining two members;
#   - our own driver connections to it are also cut (measured
#     empirically: `docker network disconnect` blackholes
#     traffic rather than issuing a fast refusal), so requests
#     hang until the shortened client-side timeout fires,
#     instead of failing instantly like node_failure's
#     ECONNREFUSED.
#
# mongo1 is configured (replica set priority 2 vs 1 for the
# others -- see rs.conf()) as the "preferred primary", so once
# the partition heals it automatically reclaims PRIMARY without
# any manual reconfiguration.
# ============================================================

PARTITION_CONTAINER = "mongo1"   # Primary, host port 27017

FAST_TIMEOUT_MS = 500

DB_NAME = "dsa5208"
COLLECTION_NAME = "network_partition_test"


# ------------------------------------------------------------
# Clients
# ------------------------------------------------------------

primary_client = MongoClient(
    "mongodb://localhost:27017/",
    directConnection=True,
    serverSelectionTimeoutMS=FAST_TIMEOUT_MS,
    connectTimeoutMS=FAST_TIMEOUT_MS,
)

secondary1_client = MongoClient(
    "mongodb://localhost:27018/",
    directConnection=True,
    serverSelectionTimeoutMS=FAST_TIMEOUT_MS,
    connectTimeoutMS=FAST_TIMEOUT_MS,
)

secondary2_client = MongoClient(
    "mongodb://localhost:27019/",
    directConnection=True,
    serverSelectionTimeoutMS=FAST_TIMEOUT_MS,
    connectTimeoutMS=FAST_TIMEOUT_MS,
)


# ------------------------------------------------------------
# WRITE / READ configuration (mirrors config1.py)
# ------------------------------------------------------------

write_collection = primary_client[DB_NAME][COLLECTION_NAME].with_options(
    write_concern=WriteConcern(w=1)
)

read_collection_1 = secondary1_client[DB_NAME][COLLECTION_NAME].with_options(
    read_concern=ReadConcern("local"),
    read_preference=Secondary(),
)

read_collection_2 = secondary2_client[DB_NAME][COLLECTION_NAME].with_options(
    read_concern=ReadConcern("local"),
    read_preference=Secondary(),
)


# ------------------------------------------------------------
# Docker network control
# ------------------------------------------------------------

def _get_network(container):
    """Return the (single) Docker network a container is attached to."""
    out = subprocess.run(
        ["docker", "inspect", container, "--format", "{{json .NetworkSettings.Networks}}"],
        check=True, capture_output=True, text=True,
    ).stdout
    import json as _json
    networks = _json.loads(out)
    return next(iter(networks))


def partition_node(container=PARTITION_CONTAINER):
    """Cut `container` off from the replication network."""
    network = _get_network(container)
    subprocess.run(
        ["docker", "network", "disconnect", network, container],
        check=True, capture_output=True,
    )
    return network


def heal_partition(container=PARTITION_CONTAINER, network=None):
    """Reconnect `container` to the replication network."""
    if network is None:
        # Fall back to the compose-generated project network name.
        network = "mongo-consistency_mongo-net"
    subprocess.run(
        ["docker", "network", "connect", network, container],
        check=True, capture_output=True,
    )


# ------------------------------------------------------------
# Wait helpers
# ------------------------------------------------------------

def wait_until_unreachable(client, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            client.admin.command("ping")
        except PyMongoError:
            return True
        time.sleep(0.1)
    return False


def wait_until_new_primary_elected(clients, timeout=30):
    """Poll the given (reachable) clients until one reports itself primary."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for client in clients:
            try:
                hello = client.admin.command("hello")
                if hello.get("isWritablePrimary"):
                    return client
            except PyMongoError:
                pass
        time.sleep(0.5)
    return None


def wait_until_primary(client, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            hello = client.admin.command("hello")
            if hello.get("isWritablePrimary"):
                return True
        except PyMongoError:
            pass
        time.sleep(0.5)
    return False
