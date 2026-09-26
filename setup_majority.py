"""Initialize/check the replica set after docker compose up -d."""
import json
import time
from pathlib import Path
from bson import json_util
from pymongo.errors import OperationFailure, PyMongoError
from majority_config import clients, docker, wait_roles, roles


def main():
    cs = clients(2000)
    try:
        deadline = time.monotonic() + 90
        for c in cs:
            while True:
                try:
                    c.admin.command('ping')
                    break
                except PyMongoError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(.5)
        try:
            cfg = cs[0].admin.command('replSetGetConfig')['config']
        except OperationFailure as e:
            if e.code != 94:
                raise
            cfg = {'_id':'rs0','members':[
                {'_id':0,'host':'mongo1:27017','priority':2},
                {'_id':1,'host':'mongo2:27017','priority':1},
                {'_id':2,'host':'mongo3:27017','priority':1}]}
            cs[0].admin.command('replSetInitiate',cfg)
        state = wait_roles(cs, {'mongo1':'PRIMARY','mongo2':'SECONDARY','mongo3':'SECONDARY'})
        actual = cs[0].admin.command('replSetGetConfig')['config']
        assert [m['host'] for m in actual['members']] == ['mongo1:27017','mongo2:27017','mongo3:27017']
        assert [m.get('priority',1) for m in actual['members']] == [2,1,1], 'Unexpected priorities; inspect existing set before changing it'
        import platform, pymongo
        evidence = {'roles':state,'replica_config':actual,
                    'mongodb':[c.admin.command('buildInfo')['version'] for c in cs],
                    'python':platform.python_version(),'pymongo':pymongo.version,
                    'docker':json.loads(docker('inspect','mongo1','mongo2','mongo3').stdout),
                    'image':json.loads(docker('image','inspect','mongo:8').stdout)}
        Path('deployment_runze.json').write_text(json_util.dumps(evidence,indent=2))
        print(json.dumps({'roles':state,'mongodb':evidence['mongodb'],'pymongo':pymongo.version}))
    finally:
        for c in cs:c.close()

if __name__ == '__main__':main()
