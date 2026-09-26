import json
import time

from pymongo.errors import PyMongoError

from network_partition_config1 import (
    write_collection,
    read_collection_1,
    read_collection_2,
    primary_client,
    secondary1_client,
    secondary2_client,
    partition_node,
    heal_partition,
    wait_until_unreachable,
    wait_until_new_primary_elected,
    wait_until_primary,
    PARTITION_CONTAINER,
)


NUM_TESTS = 60


# ============================================================
# Shared trial helper
#
# During the partition every trial's baseline write goes to
# mongo1 (the isolated primary) and hangs until the shortened
# client timeout fires. There is nothing left to test once that
# write cannot be made, so every one of the four consistency
# checks below starts by attempting it and immediately records
# "unavailable" if it fails, instead of pretending the trial ran.
# ============================================================

def try_write(doc, upsert=False):
    try:
        write_collection.replace_one({"_id": doc["_id"]}, doc, upsert=upsert)
        return True
    except PyMongoError:
        return False


# ============================================================
# 1. READ-YOUR-WRITES
# ============================================================

def test_read_your_writes():
    satisfied = violated = unavailable = 0

    for i in range(NUM_TESTS):
        old_value = 2 * i
        new_value = 2 * i + 1

        if not try_write({"_id": "x", "value": old_value}, upsert=True):
            unavailable += 1
            continue
        if not try_write({"_id": "x", "value": new_value}):
            unavailable += 1
            continue

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
# ============================================================

def test_monotonic_reads():
    satisfied = violated = unavailable = 0

    for i in range(NUM_TESTS):
        old_value = 2 * i
        new_value = 2 * i + 1

        if not try_write({"_id": "x", "value": old_value}, upsert=True):
            unavailable += 1
            continue
        if not try_write({"_id": "x", "value": new_value}):
            unavailable += 1
            continue

        try:
            first_doc = read_collection_1.find_one({"_id": "x"})
            first_value = first_doc["value"]
            second_doc = read_collection_2.find_one({"_id": "x"})
            second_value = second_doc["value"]
        except PyMongoError:
            unavailable += 1
            continue

        if second_value >= first_value:
            satisfied += 1
        else:
            violated += 1

    return satisfied, violated, unavailable


# ============================================================
# 3. MONOTONIC WRITES
# ============================================================

def test_monotonic_writes():
    satisfied = violated = unavailable = 0

    for i in range(NUM_TESTS):
        baseline = 3 * i
        first_write = 3 * i + 1
        second_write = 3 * i + 2

        if not try_write({"_id": "x", "value": baseline}, upsert=True):
            unavailable += 1
            continue
        if not try_write({"_id": "x", "value": first_write}):
            unavailable += 1
            continue
        if not try_write({"_id": "x", "value": second_write}):
            unavailable += 1
            continue

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
# ============================================================

def test_writes_follow_reads():
    satisfied = violated = unavailable = 0

    for i in range(NUM_TESTS):
        old_version = 2 * i
        new_version = 2 * i + 1

        if not try_write(
            {"_id": "x", "value": old_version, "version": old_version}, upsert=True
        ):
            unavailable += 1
            continue
        if not try_write(
            {"_id": "x", "value": new_version, "version": new_version}
        ):
            unavailable += 1
            continue

        try:
            read_doc = read_collection_1.find_one({"_id": "x"})
            read_version = read_doc["version"]
        except PyMongoError:
            unavailable += 1
            continue

        if not try_write(
            {"_id": "y", "based_on_version": read_version, "trial": i}, upsert=True
        ):
            unavailable += 1
            continue

        try:
            primary_x = write_collection.find_one({"_id": "x"})
            primary_version = primary_x["version"]
        except PyMongoError:
            unavailable += 1
            continue

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
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--smoke", action="store_true",
        help="3 trials per model per phase; the formal results file is not written",
    )
    args = parser.parse_args()
    if args.smoke:
        NUM_TESTS = 3

    print("NETWORK PARTITION -- CONFIGURATION 1")
    print("=" * 50)
    print(f"Fault target: {PARTITION_CONTAINER} (Primary, port 27017)")

    print("\nPartitioning node from the replication network...")
    network = partition_node()
    unreachable = wait_until_unreachable(primary_client)
    print(f"Network disconnected: {network}")
    print(f"Confirmed our own client can no longer reach it: {unreachable}")

    print("Waiting for the remaining two members to elect a new primary...")
    new_primary_client = wait_until_new_primary_elected(
        [secondary1_client, secondary2_client]
    )
    if new_primary_client is not None:
        port = new_primary_client.address[1]
        print(f"New primary elected on port {port}")
    else:
        print("No new primary observed within the timeout")

    during_results = run_phase("DURING PARTITION")

    print("\nHealing the partition...")
    heal_partition(network=network)
    reclaimed = wait_until_primary(primary_client, timeout=180)
    print(f"mongo1 reclaimed PRIMARY (priority takeover): {reclaimed}")
    # Give replication a moment to fully settle before measuring
    # steady-state behaviour again.
    time.sleep(2)

    after_results = run_phase("AFTER RECOVERY")

    if args.smoke:
        print("\nSmoke run: formal results file not written")
    else:
        with open("network_partition_config1_results.json", "w") as f:
            json.dump(
                {"during_partition": during_results, "after_recovery": after_results},
                f,
                indent=2,
            )

        print("\nResults written to network_partition_config1_results.json")
