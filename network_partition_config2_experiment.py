"""Isolate mongo1, test after election, reconnect, and test after recovery."""
from network_partition_config2 import CONFIG, PARTITION_CONTAINER
from normal_config2_experiment import TESTS
from config2_helpers import entry

NUM_TESTS = 60  # Per model in EACH phase: during partition and after recovery.

if __name__ == '__main__':
    entry('partition', NUM_TESTS, tuple(TESTS))
