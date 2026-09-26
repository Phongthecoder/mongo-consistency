"""Configuration 2: normal operation, 1000 trials per consistency model."""
NUM_TESTS = 1000


def test_read_your_writes(c):
    # W1 has been acknowledged. R1 uses exactly the same causal session.
    doc = c.read(c.s1, c.x, 'R1')
    return 'no_violation_observed' if doc and doc['version'] >= c.first else 'violation'


def test_monotonic_reads(c):
    from config2_helpers import Inconclusive
    first_doc = c.read(c.s1, c.x, 'R1')
    second_doc = c.read(c.s2, c.x, 'R2')
    if not first_doc:
        raise Inconclusive('First read has no version to establish a lower bound')
    return ('no_violation_observed' if second_doc and
            second_doc['version'] >= first_doc['version'] else 'violation')


def test_monotonic_writes(c):
    second_time = c.write(c.w, {'_id': c.x, 'version': c.second}, 'W2')
    c.wait_value(c.s1, c.x, c.second, 'observe_W2', timeout=1)
    # Continue observing after W2; do not terminate at its first appearance.
    for _ in range(10):
        doc = c.read(c.s1, c.x, 'post_W2_read')
        if not doc or doc['version'] < c.second:
            return 'violation'
    first_op = c.oplog(1, c.t1, 'audit_W1_oplog', c.w.full_name, c.x)
    second_op = c.oplog(1, second_time, 'audit_W2_oplog', c.w.full_name, c.x)
    return 'no_violation_observed' if first_op['ts'] < second_op['ts'] else 'violation'


def test_writes_follow_reads(c):
    from config2_helpers import Inconclusive
    read_doc = c.read(c.s1, c.x, 'R1')
    if not read_doc:
        raise Inconclusive('First read has no dependency version')
    read_version = read_doc['version']
    dependent_time = c.write(c.w, {'_id': c.y, 'version': 1,
                                   'based_on_version': read_version}, 'dependent_write')
    primary_doc = c.read(c.w, c.x, 'check_primary_dependency')
    if not primary_doc or primary_doc['version'] < read_version:
        return 'violation'
    c.wait_value(c.s1, c.y, 1, 'observe_dependent_write')
    secondary_doc = c.read(c.s1, c.x, 'check_secondary_dependency')
    if not secondary_doc or secondary_doc['version'] < read_version:
        return 'violation'
    source_stage = 'W1' if read_version == c.first else 'baseline_write'
    source_time = next(op['operationTime'] for op in c.trial['operations']
                       if op['stage'] == source_stage)
    source_op = c.oplog(1, source_time, 'audit_source_oplog', c.w.full_name, c.x)
    dependent_op = c.oplog(1, dependent_time, 'audit_dependent_oplog', c.w.full_name, c.y)
    return 'no_violation_observed' if source_op['ts'] < dependent_op['ts'] else 'violation'


TESTS = {'RYW': test_read_your_writes, 'MR': test_monotonic_reads,
         'MW': test_monotonic_writes, 'WFR': test_writes_follow_reads}

if __name__ == '__main__':
    from config2_helpers import entry
    entry('normal', NUM_TESTS)
