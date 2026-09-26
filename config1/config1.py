"""CONFIGURATION 1: w=1 / local / secondary / causal OFF."""
from pymongo import MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern
from pymongo.read_preferences import Secondary, Primary

DB_NAME = 'dsa5208_config1'
NODES = ('mongo1', 'mongo2', 'mongo3')
URI = 'mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0'
CONFIG = {'writeConcern':1,'readConcern':'local',
          'readPreference':'secondary','causalConsistency':False,
          'replicaSet':'rs0','retryReads':False,'retryWrites':False,
          'maxTimeMS':2000,'socketTimeoutMS':4000}

def create_client(timeout_ms=30000, monitor=None):
    return MongoClient(URI, serverSelectionTimeoutMS=timeout_ms,
                       connectTimeoutMS=timeout_ms, socketTimeoutMS=4000,
                       retryReads=False, retryWrites=False,
                       event_listeners=[monitor] if monitor else [])

def create_collections(client, name):
    write_collection = client[DB_NAME][name].with_options(
        write_concern=WriteConcern(w=1),
        read_concern=ReadConcern('local'), read_preference=Primary())
    read_collection_1 = write_collection.with_options(
        read_preference=Secondary(tag_sets=[{'node':'mongo2'}]))
    read_collection_2 = write_collection.with_options(
        read_preference=Secondary(tag_sets=[{'node':'mongo3'}]))
    return write_collection, read_collection_1, read_collection_2

def trial_session(client):
    # Causal consistency OFF: no explicit session is created, so each operation
    # runs in its own implicit session and carries no afterClusterTime.
    return None
