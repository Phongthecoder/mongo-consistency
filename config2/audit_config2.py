"""Audit Config 2 settings, same-session causality and measured predicates."""
import hashlib
import json
import sys
from pathlib import Path
from collections import Counter,defaultdict
from bson import json_util


def audit(path):
    path=Path(path)
    assert (path/'COMPLETE').exists(),'Incomplete run'
    manifest=json.loads((path/'manifest.json').read_text())
    for name,digest in manifest['source_sha256'].items():
        assert hashlib.sha256((path/'source'/name).read_bytes()).hexdigest()==digest
    database_name=manifest.get('database_name','dsa5208_config2')
    counts=defaultdict(Counter);errors=Counter();stages=Counter();examples={};ids=set()
    roles={};barriers=0;last_roles=None;command_counts=Counter();causal_reads=0;faults=[]
    for line in (path/'history.jsonl').open():
        r=json_util.loads(line)
        if r['type']=='recovery':
            assert len(r['readbacks'])==3 and all(x['version']==1 for x in r['readbacks'])
            assert r['roles']=={'mongo1':'PRIMARY','mongo2':'SECONDARY','mongo3':'SECONDARY'}
            last_roles=r['roles'];barriers+=1
        if r['type']=='fault_start':faults.append(r)
        if r['type']=='phase_start':roles[r['phase']]=r['roles']
        if r['type']!='trial':continue
        assert r['case'] not in ids;ids.add(r['case'])
        assert r['causal_consistency'] is True
        requests={};last_time=None
        for e in r['events']:
            if e['event']=='started':
                cmd=e['payload'];requests[e['request_id']]=e
                if cmd.get('$db')!=database_name:continue
                command_counts[e['command']]+=1
                assert cmd['lsid']==r['session_id'],'Different session inside trial'
                node=e['node'][0]
                if e['command']=='update':
                    assert cmd['writeConcern']['w']=='majority'
                    assert roles[r['phase']][node]=='PRIMARY'
                elif e['command']=='find':
                    assert cmd['readConcern']['level']=='majority'
                    assert last_time is not None
                    assert cmd['readConcern']['afterClusterTime']>=last_time,'Missing/old causal lower bound'
                    causal_reads+=1
                    pref=cmd.get('$readPreference',{'mode':'primary'})
                    if pref['mode']=='secondary':
                        assert roles[r['phase']][node]=='SECONDARY'
                        assert pref['tags']==[{'node':node}]
                    else:
                        assert pref['mode']=='primary' and roles[r['phase']][node]=='PRIMARY'
            elif e['event']=='succeeded':
                start=requests[e['request_id']]
                if start['payload'].get('$db')==database_name and e.get('operationTime') is not None:
                    if last_time is None or e['operationTime']>last_time:last_time=e['operationTime']
        ops=r['operations'];by=defaultdict(list)
        for op in ops:by[op['stage']].append(op)
        outcome=r['outcome'];model=r['model']
        if outcome=='unavailable':
            assert any(not op['ok'] for op in ops)
            errors[r['error']]+=1;stages[r['stage']]+=1
        elif outcome=='inconclusive':assert r.get('reason')
        else:
            assert all(op['ok'] for op in ops)
            assert by['W1'][0]['value']['acknowledged']
            first=3*r['trial']+1
            if model=='RYW':
                d=by['R1'][0]['value'];valid=bool(d and d['version']>=first)
            elif model=='MR':
                a=by['R1'][0]['value'];b=by['R2'][0]['value'];assert a
                valid=bool(b and b['version']>=a['version'])
            elif model=='MW':
                assert by['W2'][0]['value']['acknowledged']
                second=first+1
                regressed=any(not x['value'] or x['value']['version']<second for x in by['post_W2_read'])
                if regressed:valid=False
                else:
                    assert len(by['post_W2_read'])==10
                    a=by['audit_W1_oplog'][0]['value'];b=by['audit_W2_oplog'][0]['value']
                    assert a['ts']==by['W1'][0]['operationTime'] and b['ts']==by['W2'][0]['operationTime']
                    valid=a['ts']<b['ts']
            else:
                dependency=by['R1'][0]['value']['version'];assert by['dependent_write'][0]['value']['acknowledged']
                a=by['check_primary_dependency'][0]['value']
                valid=bool(a and a['version']>=dependency)
                if valid:
                    b=by['check_secondary_dependency'][0]['value'];valid=bool(b and b['version']>=dependency)
                if valid:
                    source=by['audit_source_oplog'][0]['value'];dependent=by['audit_dependent_oplog'][0]['value']
                    source_stage='W1' if dependency==first else 'baseline_write'
                    assert source['ts']==by[source_stage][0]['operationTime']
                    assert dependent['ts']==by['dependent_write'][0]['operationTime']
                    valid=source['ts']<dependent['ts']
            assert outcome==('no_violation_observed' if valid else 'violation'),r['case']
        counts[(r['phase'],model)][outcome]+=1
        examples.setdefault((r['phase'],model,outcome),r)
    phases={'normal':['normal'],'node':['node_during','node_after'],
            'partition':['partition_during','partition_after'],'ryw':['normal']}[manifest['scenario']]
    for phase in phases:
        for model in manifest['models']:
            assert sum(counts[(phase,model)].values())==manifest['trials_per_model_per_phase']
    summary=json.loads((path/'summary.json').read_text())
    for row in summary:
        for key in ['no_violation_observed','violation','unavailable','inconclusive']:
            assert row[key]==counts[(row['phase'],row['model'])][key]
    assert last_roles=={'mongo1':'PRIMARY','mongo2':'SECONDARY','mongo3':'SECONDARY'}
    assert barriers>=2
    if manifest['scenario'] in ('node','partition'):assert len(faults)==1
    total=Counter()
    for c in counts.values():total.update(c)
    result={'audit_passed':True,'scenario':manifest['scenario'],'trials':len(ids),
            'outcomes':dict(total),'errors':dict(errors),'unavailable_stages':dict(stages),
            'application_commands':dict(command_counts),'verified_causal_reads':causal_reads,
            'verified_recovery_barriers':barriers,'final_roles':last_roles,'groups':summary,
            'fault_roles':[f['roles'] for f in faults]}
    (path/'audit.json').write_text(json.dumps(result,indent=2))
    (path/'examples.json').write_text(json_util.dumps(list(examples.values()),indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='groups'},indent=2))
    return result

if __name__=='__main__':
    for arg in sys.argv[1:]:audit(arg)
