import json
import time

from pymongo.errors import PyMongoError

from node_failure_config1 import (
    write_collection,
    read_collection_1,
    read_collection_2,
    secondary1_client,
    stop_node,
    start_node,
    wait_until_unreachable,
    wait_until_secondary,
    FAILURE_CONTAINER,
)


NUM_TESTS = 500


def wait_for_value(collection, expected_value, timeout=5):
    """Wait until a (reachable) replica has received a particular value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            doc = collection.find_one({"_id": "x"})
            if doc is not None and doc["value"] == expected_value:
                return True
        except PyMongoError:
            pass
        time.sleep(0.01)
    return False


# ============================================================
# 1. READ-YOUR-WRITES
#
# Pattern:      W(x, new) -> R(x) on Secondary 1 (fault target)
# Violation:    read returns the old value
# Unavailable:  read raises a connectivity error
# ============================================================

def test_read_your_writes():
    satisfied = violated = unavailable = 0

    for i in range(NUM_TESTS):
        old_value = 2 * i
        new_value = 2 * i + 1

        # Both writes go to the primary, which stays healthy
        # throughout this fault, so they always succeed.
        write_collection.replace_one(
            {"_id": "x"}, {"_id": "x", "value": old_value}, upsert=True,
        )
        write_collection.replace_one(
            {"_id": "x"}, {"_id": "x", "value": new_value},
        )

        try:
            doc = read_collection_1.find_one({"_id": "x"})
            if doc is not None and doc["value"] == new_value:
                satisfied += 1
            else:
                violated += 1
        except PyMongoError:
            unavailable += 1

    return satisfied, violated, unavailable


# ============================================================
# 2. MONOTONIC READS
#
# Pattern:      R(x) on Secondary 1 (fault target) -> R(x) on Secondary 2
# Violation:    second read is older than the first
# Unavailable:  the first read (Secondary 1) raises a connectivity error
# ============================================================

def test_monotonic_reads():
    satisfied = violated = unavailable = 0

    for i in range(NUM_TESTS):
        old_value = 2 * i
        new_value = 2 * i + 1

        write_collection.replace_one(
            {"_id": "x"}, {"_id": "x", "value": old_value}, upsert=True,
        )
        # Secondary 2 is never the fault target, so it is a
        # valid anchor for "the baseline has left the primary".
        wait_for_value(read_collection_2, old_value)

        write_collection.replace_one(
            {"_id": "x"}, {"_id": "x", "value": new_value},
        )

        try:
            first_doc = read_collection_1.find_one({"_id": "x"})
            first_value = first_doc["value"]
        except PyMongoError:
            unavailable += 1
            continue

        second_doc = read_collection_2.find_one({"_id": "x"})
        second_value = second_doc["value"]

        if second_value >= first_value:
            satisfied += 1
        else:
            violated += 1

    return satisfied, violated, unavailable


# ============================================================
# 3. MONOTONIC WRITES
#
# Pattern:      W(x, a) -> W(x, b), observed on Secondary 1 (fault target)
# Violation:    b is observed, then a is observed afterward
# Unavailable:  Secondary 1 never answers during the observation window
# ============================================================

def test_monotonic_writes():
    satisfied = violated = unavailable = 0

    for i in range(NUM_TESTS):
        baseline = 3 * i
        first_write = 3 * i + 1
        second_write = 3 * i + 2

        write_collection.replace_one(
            {"_id": "x"}, {"_id": "x", "value": baseline}, upsert=True,
        )

        write_collection.replace_one(
            {"_id": "x"}, {"_id": "x", "value": first_write},
        )
        write_collection.replace_one(
            {"_id": "x"}, {"_id": "x", "value": second_write},
        )

        seen_second_write = False
        violation_found = False
        ever_answered = False

        deadline = time.time() + 1.0
        while time.time() < deadline:
            try:
                doc = read_collection_1.find_one({"_id": "x"})
            except PyMongoError:
                continue

            if doc is None:
                continue

            ever_answered = True
            value = doc["value"]

            if value == second_write:
                seen_second_write = True

            if seen_second_write and value == first_write:
                violation_found = True
                break

            if seen_second_write:
                break

        if not ever_answered:
            unavailable += 1
        elif violation_found:
            violated += 1
        else:
            satisfied += 1

    return satisfied, violated, unavailable


# ============================================================
# 4. WRITES-FOLLOW-READS
#
# Pattern:      R(x) on Secondary 1 (fault target) -> W(y, based on x)
# Violation:    the primary's version of x is older than what was read
# Unavailable:  the read on Secondary 1 raises a connectivity error
# ============================================================

def test_writes_follow_reads():
    satisfied = violated = unavailable = 0

    for i in range(NUM_TESTS):
        old_version = 2 * i
        new_version = 2 * i + 1

        write_collection.replace_one(
            {"_id": "x"},
            {"_id": "x", "value": old_version, "version": old_version},
            upsert=True,
        )
        write_collection.replace_one(
            {"_id": "x"},
            {"_id": "x", "value": new_version, "version": new_version},
        )

        try:
            read_doc = read_collection_1.find_one({"_id": "x"})
            read_version = read_doc["version"]
        except PyMongoError:
            unavailable += 1
            continue

        write_collection.replace_one(
            {"_id": "y"},
            {"_id": "y", "based_on_version": read_version, "trial": i},
            upsert=True,
        )

        primary_x = write_collection.find_one({"_id": "x"})
        primary_version = primary_x["version"]

        if primary_version >= read_version:
            satisfied += 1
        else:
            violated += 1

    return satisfied, violated, unavailable


TESTS = [
    ("Read-your-writes", test_read_your_writes),
    ("Monotonic reads", test_monotonic_reads),
    ("Monotonic writes", test_monotonic_writes),
    ("Writes-follow-reads", test_writes_follow_reads),
]


def run_phase(label):
    print(f"\n--- {label} ---")
    phase_results = {}
    for name, fn in TESTS:
        satisfied, violated, unavailable = fn()
        phase_results[name] = {
            "satisfied": satisfied,
            "violated": violated,
            "unavailable": unavailable,
        }
        print(f"\n{name}")
        print(f"  Trials:        {NUM_TESTS}")
        print(f"  Satisfied:     {satisfied}")
        print(f"  Violated:      {violated}")
        print(f"  Unavailable:   {unavailable}")
        print(f"  Violation %:   {100 * violated / NUM_TESTS:.2f}%")
        print(f"  Unavailable %: {100 * unavailable / NUM_TESTS:.2f}%")
    return phase_results


if __name__ == "__main__":
    print("NODE FAILURE -- CONFIGURATION 1")
    print("=" * 50)
    print(f"Fault target: {FAILURE_CONTAINER} (Secondary 1, port 27018)")

    print("\nStopping node...")
    stop_node()
    unreachable = wait_until_unreachable(secondary1_client)
    print(f"Confirmed unreachable: {unreachable}")

    during_results = run_phase("DURING FAILURE")

    print("\nRestarting node...")
    start_node()
    rejoined = wait_until_secondary(secondary1_client)
    print(f"Confirmed rejoined as secondary: {rejoined}")
    # Give replication a moment to catch up fully before measuring
    # steady-state behaviour again.
    time.sleep(2)

    after_results = run_phase("AFTER RECOVERY")

    with open("node_failure_results.json", "w") as f:
        json.dump(
            {"during_failure": during_results, "after_recovery": after_results},
            f,
            indent=2,
        )

    print("\nResults written to node_failure_results.json")
