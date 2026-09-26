"""Configuration 1 partition settings and election/reconnection helpers."""
import time
from config1 import CONFIG
from config1_helpers import docker, project_network

PARTITION_CONTAINER = 'mongo1'
FAST_TIMEOUT_MS = 500


def partition_node():
    network = project_network()
    docker('network', 'disconnect', network, PARTITION_CONTAINER)
    return network


def heal_partition(network):
    return docker('network', 'connect', '--alias', 'mongo1', network, PARTITION_CONTAINER)


def wait_for_election(worker, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        roles = worker.request('status')
        if roles['mongo1'] == 'UNREACHABLE' and 'PRIMARY' in (roles['mongo2'], roles['mongo3']):
            return roles
        time.sleep(.5)
    raise RuntimeError('Partition or election among remaining members was not verified')
