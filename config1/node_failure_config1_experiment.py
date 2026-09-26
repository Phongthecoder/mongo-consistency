"""Stop mongo2, test all four models, recover, and test again."""
from node_failure_config1 import CONFIG, FAILURE_CONTAINER
from normal_config1_experiment import TESTS
from config1_helpers import entry

NUM_TESTS = 500  # Per model in EACH phase: during failure and after recovery.

if __name__ == '__main__':
    entry('node', NUM_TESTS, tuple(TESTS))
