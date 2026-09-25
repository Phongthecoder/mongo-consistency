"""Optional standalone RYW experiment; separate from the formal three-scenario run."""
from config2_helpers import entry

NUM_TESTS = 1000

if __name__ == '__main__':
    entry('ryw', NUM_TESTS, ('RYW',))
