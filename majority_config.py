"""One configuration, fixed nodes, no causal session. Original config1 is retained."""
import os
import shutil
import subprocess
import time
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import Secondary, Primary
from pymongo.write_concern import WriteConcern

NODES = ('mongo1', 'mongo2', 'mongo3')
PORTS = (27017, 27018, 27019)
CONFIG = dict(writeConcern='majority', readConcern='majority',
              readPreference='secondary', causalConsistency=False,
              directConnection=True, retryReads=False, retryWrites=False,
              wtimeoutMS=2000, maxTimeMS=2000, socketTimeoutMS=4000)

def docker(*args, check=True):
    executable = shutil.which('docker') or '/opt/homebrew/bin/docker'
    context = os.environ.get('LAB_DOCKER_CONTEXT')
    if not context and not os.environ.get('DOCKER_HOST') and not os.environ.get('DOCKER_CONTEXT'):
        probe = subprocess.run([executable, 'context', 'inspect', 'colima-consistency-lab'], capture_output=True)
        if probe.returncode == 0:
            context = 'colima-consistency-lab'
    command = [executable] + (['--context', context] if context else []) + list(args)
    return subprocess.run(command, check=check, text=True, capture_output=True, timeout=90)

def clients(timeout=500, monitor=None):
    return [MongoClient(f'mongodb://localhost:{port}/', directConnection=True,
                       serverSelectionTimeoutMS=timeout, connectTimeoutMS=timeout,
                       socketTimeoutMS=4000, retryReads=False, retryWrites=False,
                       event_listeners=[monitor] if monitor else []) for port in PORTS]

def collection(client, name, secondary=False):
    return client.runze_majority[name].with_options(
        read_concern=ReadConcern('majority'),
        write_concern=WriteConcern(w='majority', wtimeout=2000),
        read_preference=Secondary() if secondary else Primary())

def roles(cs):
    result = {}
    for node, client in zip(NODES, cs):
        try:
            h = client.admin.command('hello')
            result[node] = 'PRIMARY' if h.get('isWritablePrimary') else ('SECONDARY' if h.get('secondary') else 'OTHER')
        except PyMongoError:
            result[node] = 'UNREACHABLE'
    return result

def wait_roles(cs, expected, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = roles(cs)
        if all(state[n] == role for n, role in expected.items()):
            return state
        time.sleep(.5)
    raise RuntimeError(f'Role wait failed: expected={expected}, actual={state}')

def network():
    import json
    networks = json.loads(docker('inspect', 'mongo1', '--format', '{{json .NetworkSettings.Networks}}').stdout)
    if len(networks) != 1:
        raise RuntimeError(f'Expected one network, got {networks}')
    return next(iter(networks))
