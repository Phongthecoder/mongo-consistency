"""Configuration 1 node-failure settings; concerns and sessions are in config1.py."""
from config1 import CONFIG
from config1_helpers import docker

FAILURE_CONTAINER = 'mongo2'
FAST_TIMEOUT_MS = 500


def stop_node():
    return docker('stop', FAILURE_CONTAINER)


def start_node():
    return docker('start', FAILURE_CONTAINER)
