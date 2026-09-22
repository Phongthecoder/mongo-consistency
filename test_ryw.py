import time

from pymongo import MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern


# ============================================================
# Configuration 1
# ============================================================
# Write concern:       w = 1
# Read concern:        local
# Read target:         secondary
# Causal consistency:  OFF (no session is used)
# ============================================================

NUM_TESTS = 1000

# Direct connection to primary
primary = MongoClient(
    "mongodb://localhost:27017/",
    directConnection=True,
)

# Direct connection to mongo2, which we verified is a secondary
secondary = MongoClient(
    "mongodb://localhost:27018/",
    directConnection=True,
)


primary_col = primary["dsa5208"]["ryw"].with_options(
    write_concern=WriteConcern(w=1)
)

secondary_col = secondary["dsa5208"]["ryw"].with_options(
    read_concern=ReadConcern("local")
)


good_ryw = 0
bad_ryw = 0


for i in range(NUM_TESTS):

    # --------------------------------------------------------
    # 1. Establish a known baseline
    #
    # Use a unique value for every trial so that we know
    # exactly which version the secondary has received.
    # --------------------------------------------------------

    old_value = 2 * i
    new_value = 2 * i + 1

    primary_col.replace_one(
        {"_id": "x"},
        {"_id": "x", "value": old_value},
        upsert=True,
    )

    # Wait until the secondary has definitely received
    # the baseline value.
    while True:
        doc = secondary_col.find_one({"_id": "x"})

        if doc is not None and doc["value"] == old_value:
            break

        time.sleep(0.001)

    # --------------------------------------------------------
    # 2. Tested write
    #
    # w=1 means MongoDB may acknowledge as soon as the
    # primary accepts this write.
    # --------------------------------------------------------

    result = primary_col.replace_one(
        {"_id": "x"},
        {"_id": "x", "value": new_value},
    )

    # --------------------------------------------------------
    # 3. Immediately read from the secondary
    #
    # readConcern = local
    # --------------------------------------------------------

    doc = secondary_col.find_one({"_id": "x"})
    observed_value = doc["value"]

    # --------------------------------------------------------
    # 4. Check RYW
    # --------------------------------------------------------

    if observed_value == new_value:
        good_ryw += 1
    else:
        bad_ryw += 1


# ============================================================
# Results
# ============================================================

print("\n========== RYW Experiment ==========")
print("Configuration:")
print("  Write concern:       w=1")
print("  Read concern:        local")
print("  Read target:         secondary")
print("  Causal consistency:  OFF")
print()

print(f"Number of trials:       {NUM_TESTS}")
print(f"RYW satisfied:          {good_ryw}")
print(f"RYW violated:           {bad_ryw}")
print(f"Violation rate:         {bad_ryw / NUM_TESTS:.2%}")
