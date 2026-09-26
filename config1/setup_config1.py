"""Add node tags and verify the replica-set client and deployment."""
from pathlib import Path
from bson import json_util
from config1_helpers import Worker, recover, docker

if __name__ == '__main__':
    evidence = []
    with Worker() as worker:
        recover(worker, lambda kind, **data: evidence.append({'type': kind, **data}))
        evidence.append({'type': 'configuration', 'value': worker.request('configure')})
        recover(worker, lambda kind, **data: evidence.append({'type': kind, **data}))
        versions = worker.request('versions')
        evidence.append({'type': 'versions', 'value': versions})
        print(json_util.dumps(versions, indent=2))
    evidence.append({'type': 'image', 'value': docker('image', 'inspect', 'project1-client-config1:1').stdout})
    Path('config1_deployment.json').write_text(json_util.dumps(evidence, indent=2))
