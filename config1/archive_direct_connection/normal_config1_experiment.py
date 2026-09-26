import time

from config1 import (
    write_collection,
    read_collection_1,
    read_collection_2,
)


NUM_TESTS = 1000


def wait_for_value(collection, expected_value):
    """Wait until a replica has received a particular value."""
    while True:
        doc = collection.find_one({"_id": "x"})

        if doc is not None and doc["value"] == expected_value:
            return

        time.sleep(0.001)


# ============================================================
# 1. READ-YOUR-WRITES
#
# Pattern:
#       W(x, new) -> R(x)
#
# Violation:
#       subsequent read observes old value
# ============================================================

def test_read_your_writes():

    satisfied = 0
    violated = 0

    for i in range(NUM_TESTS):

        old_value = 2 * i
        new_value = 2 * i + 1

        # Establish baseline
        write_collection.replace_one(
            {"_id": "x"},
            {"_id": "x", "value": old_value},
            upsert=True,
        )

        # Make sure our test starts from a known state.
        wait_for_value(read_collection_1, old_value)

        # W(x, new)
        write_collection.replace_one(
            {"_id": "x"},
            {"_id": "x", "value": new_value},
        )

        # R(x)
        doc = read_collection_1.find_one({"_id": "x"})

        if doc["value"] == new_value:
            satisfied += 1
        else:
            violated += 1

    return satisfied, violated


# ============================================================
# 2. MONOTONIC READS
#
# Pattern:
#       R(x, version1) -> R(x, version2)
#
# Violation:
#       version2 is older than version1
# ============================================================

def test_monotonic_reads():

    satisfied = 0
    violated = 0

    for i in range(NUM_TESTS):

        old_value = 2 * i
        new_value = 2 * i + 1

        # ----------------------------------------------------
        # 1. Establish old state everywhere
        # ----------------------------------------------------

        write_collection.replace_one(
            {"_id": "x"},
            {"_id": "x", "value": old_value},
            upsert=True,
        )

        wait_for_value(read_collection_1, old_value)
        wait_for_value(read_collection_2, old_value)

        # ----------------------------------------------------
        # 2. Write a newer version
        # ----------------------------------------------------

        write_collection.replace_one(
            {"_id": "x"},
            {"_id": "x", "value": new_value},
        )

        # ----------------------------------------------------
        # 3. First read from secondary 1
        # ----------------------------------------------------

        first_doc = read_collection_1.find_one({"_id": "x"})
        first_value = first_doc["value"]

        # ----------------------------------------------------
        # 4. Second read from secondary 2
        # ----------------------------------------------------

        second_doc = read_collection_2.find_one({"_id": "x"})
        second_value = second_doc["value"]

        # ----------------------------------------------------
        # 5. Check monotonic reads
        # ----------------------------------------------------

        if second_value >= first_value:
            satisfied += 1
        else:
            violated += 1

    return satisfied, violated

# ============================================================
# 3. MONOTONIC WRITES
#
# Pattern:
#       W(x, version1) -> W(x, version2)
#
# Violation:
#       writes become visible/applied in reverse order
# ============================================================

def test_monotonic_writes():
    satisfied = 0
    violated = 0

    for i in range(NUM_TESTS):

        baseline = 3 * i
        first_write = 3 * i + 1
        second_write = 3 * i + 2

        # -----------------------------------------------
        # 1. Establish a known baseline
        # -----------------------------------------------

        write_collection.replace_one(
            {"_id": "x"},
            {"_id": "x", "value": baseline},
            upsert=True,
        )

        wait_for_value(read_collection_1, baseline)

        # -----------------------------------------------
        # 2. First write: W(x, a)
        # -----------------------------------------------

        result1 = write_collection.replace_one(
            {"_id": "x"},
            {"_id": "x", "value": first_write},
        )

        # replace_one() returns only after the w=1
        # acknowledgement has been received.

        # -----------------------------------------------
        # 3. Second write: W(x, b)
        # -----------------------------------------------

        result2 = write_collection.replace_one(
            {"_id": "x"},
            {"_id": "x", "value": second_write},
        )

        # -----------------------------------------------
        # 4. Observe replication
        # -----------------------------------------------

        seen_second_write = False
        violation_found = False

        deadline = time.time() + 1.0

        while time.time() < deadline:

            doc = read_collection_1.find_one({"_id": "x"})

            if doc is None:
                continue

            value = doc["value"]

            # We have observed the second write.
            if value == second_write:
                seen_second_write = True

            # Once b has been observed, seeing a afterward
            # would mean the writes became visible backward.
            if seen_second_write and value == first_write:
                violation_found = True
                break

            # Once the secondary has reached b, normally
            # there is no reason to wait for the full second.
            if seen_second_write:
                break

        if violation_found:
            violated += 1
        else:
            satisfied += 1

    return satisfied, violated


# ============================================================
# 4. WRITES-FOLLOW-READS
#
# Pattern:
#       R(x, version1) -> W(x, version2)
#
# Violation:
#       write is applied to a state older than version1
# ============================================================

def test_writes_follow_reads():

    satisfied = 0
    violated = 0

    for i in range(NUM_TESTS):

        old_version = 2 * i
        new_version = 2 * i + 1

        # -----------------------------------------------
        # 1. Establish a known state
        # -----------------------------------------------

        write_collection.replace_one(
            {"_id": "x"},
            {
                "_id": "x",
                "value": old_version,
                "version": old_version,
            },
            upsert=True,
        )

        wait_for_value(read_collection_1, old_version)

        # Create a newer state
        write_collection.replace_one(
            {"_id": "x"},
            {
                "_id": "x",
                "value": new_version,
                "version": new_version,
            },
        )

        # -----------------------------------------------
        # 2. Client reads from secondary
        # -----------------------------------------------

        read_doc = read_collection_1.find_one({"_id": "x"})
        read_version = read_doc["version"]

        # -----------------------------------------------
        # 3. Client subsequently writes
        # -----------------------------------------------

        write_collection.replace_one(
            {"_id": "y"},
            {
                "_id": "y",
                "based_on_version": read_version,
                "trial": i,
            },
            upsert=True,
        )

        # -----------------------------------------------
        # 4. Inspect primary state
        # -----------------------------------------------

        primary_x = write_collection.find_one({"_id": "x"})
        primary_version = primary_x["version"]

        if primary_version >= read_version:
            satisfied += 1
        else:
            violated += 1

    return satisfied, violated


TESTS = [
    ("Read-your-writes", test_read_your_writes),
    ("Monotonic reads", test_monotonic_reads),
    ("Monotonic writes", test_monotonic_writes),
    ("Writes-follow-reads", test_writes_follow_reads),
]


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

    import json

    print("NORMAL CONDITION — CONFIGURATION 1")
    print("=" * 50)

    results = {}

    for name, fn in TESTS:
        good, bad = fn()
        results[name] = {"satisfied": good, "violated": bad}

        print(f"\n{name}")
        print(f"  Trials:      {NUM_TESTS}")
        print(f"  Satisfied:   {good}")
        print(f"  Violated:    {bad}")
        print(f"  Violation %: {100 * bad / NUM_TESTS:.2f}%")

    if args.smoke:
        print("\nSmoke run: formal results file not written")
    else:
        with open("normal_config1_results.json", "w") as f:
            json.dump(results, f, indent=2)

        print("\nResults written to normal_config1_results.json")
