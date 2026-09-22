from pymongo import MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern
from pymongo.read_preferences import Secondary


# ============================================================
# CONFIGURATION 1
# ============================================================
# Write concern:       w = 1
# Read concern:        local
# Read preference:     secondary
# Causal consistency:  OFF
# ============================================================


# ------------------------------------------------------------
# Clients
# ------------------------------------------------------------

primary_client = MongoClient(
    "mongodb://localhost:27017/",
    directConnection=True,
)

secondary1_client = MongoClient(
    "mongodb://localhost:27018/",
    directConnection=True,
)

secondary2_client = MongoClient(
    "mongodb://localhost:27019/",
    directConnection=True,
)


DB_NAME = "dsa5208"
COLLECTION_NAME = "consistency_test"


# ------------------------------------------------------------
# WRITE configuration
# ------------------------------------------------------------

write_collection = primary_client[DB_NAME][COLLECTION_NAME].with_options(
    write_concern=WriteConcern(w=1)
)


# ------------------------------------------------------------
# READ configuration
# ------------------------------------------------------------

read_collection_1 = secondary1_client[DB_NAME][COLLECTION_NAME].with_options(
    read_concern=ReadConcern("local"),
    read_preference=Secondary(),
)

read_collection_2 = secondary2_client[DB_NAME][COLLECTION_NAME].with_options(
    read_concern=ReadConcern("local"),
    read_preference=Secondary(),
)


# ------------------------------------------------------------
# CAUSAL CONSISTENCY
# ------------------------------------------------------------

# No session with causal_consistency=True is created.
# Therefore causal consistency is OFF.