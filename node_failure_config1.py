import subprocess
import time

from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern
from pymongo.read_preferences import Secondary


# ============================================================
# CONFIGURATION 1 -- NODE FAILURE fault
# ============================================================
# Same tunables as config1.py:
#   Write concern:       w = 1
#   Read concern:        local
#   Read preference:     secondary
#   Causal consistency:  OFF
#
# The fault target is Secondary 1 (container "mongo2", host
# port 27018) -- the node every one of the four consistency
# experiments reads from at least once. The mongod PROCESS is
# stopped with `docker stop`, so the container still exists
# (its data directory is untouched) but nothing is listening
# on the port: the driver's TCP connect is refused almost
# immediately (ECONNREFUSED).
#
# That fast-refusal behaviour is what distinguishes a "node
# failure" from a "network partition" (see
# network_partition_config1.py), where the process keeps
# running and packets are silently dropped instead.
# ============================================================

FAILURE_CONTAINER = "mongo2"   # Secondary 1, host port 27018

# config1.py leaves timeouts at PyMongo's defaults (30s server
# selection). That is unusable here: hundreds of trials against
# a genuinely dead node would otherwise take 30s each. Shorten
# it so a dead node fails fast.
FAST_TIMEOUT_MS = 500

DB_NAME = "dsa5208"
COLLECTION_NAME = "node_failure_test"


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
# Docker control
# ------------------------------------------------------------

def stop_node(container=FAILURE_CONTAINER):
    """Simulate a crash: stop the mongod process/container."""
    subprocess.run(["docker", "stop", container], check=True, capture_output=True)


def start_node(container=FAILURE_CONTAINER):
    """Recover from the crash: restart the container."""
    subprocess.run(["docker", "start", container], check=True, capture_output=True)


# ------------------------------------------------------------
# Wait helpers
# ------------------------------------------------------------

def wait_until_unreachable(client, timeout=10):
    """Block until `client`'s target stops answering pings."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            client.admin.command("ping")
        except PyMongoError:
            return True
        time.sleep(0.1)
    return False


def wait_until_secondary(client, timeout=60):
    """Block until `client`'s target rejoins as a healthy secondary."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            hello = client.admin.command("hello")
            if hello.get("secondary"):
                return True
        except PyMongoError:
            pass
        time.sleep(0.5)
    return False
