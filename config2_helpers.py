"""Shared evidence checks, container worker and host experiment utilities."""
import argparse
import csv
import fcntl
import hashlib
import json
import os
import selectors
import shutil
import subprocess
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from bson import json_util
from pymongo import MongoClient, monitoring
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import Nearest
from pymongo.write_concern import WriteConcern
from config2 import CONFIG, DB_NAME, NODES, create_client, create_collections, causal_session

ROOT=Path(__file__).resolve().parent
MODELS=('RYW','MR','MW','WFR')
HEALTHY={'mongo1':'PRIMARY','mongo2':'SECONDARY','mongo3':'SECONDARY'}
class Inconclusive(Exception):pass

class Monitor(monitoring.CommandListener):
    def __init__(self):self.events=[]
    def started(self,e):
        self.events.append({'event':'started','command':e.command_name,'node':e.connection_id,
                            'request_id':e.request_id,'payload':dict(e.command)})
    def succeeded(self,e):
        self.events.append({'event':'succeeded','command':e.command_name,'request_id':e.request_id,
                            'duration_us':e.duration_micros,'operationTime':e.reply.get('operationTime'),
                            'writeConcernError':e.reply.get('writeConcernError')})
    def failed(self,e):
        self.events.append({'event':'failed','command':e.command_name,'request_id':e.request_id,
                            'duration_us':e.duration_micros,'failure':e.failure})

class DatabaseWorker:
    def __init__(self):
        self.monitor=Monitor()
        self.client=create_client(500,self.monitor)
        self.direct=[MongoClient(f'mongodb://{n}:27017/',directConnection=True,
                    serverSelectionTimeoutMS=500,connectTimeoutMS=500,socketTimeoutMS=4000,
                    retryReads=False,retryWrites=False,event_listeners=[self.monitor]) for n in NODES]
        self.phase=None;self.runid=None;self.session=None
    def status(self):
        result={}
        for n,c in zip(NODES,self.direct):
            try:
                h=c.admin.command('hello')
                result[n]='PRIMARY' if h.get('isWritablePrimary') else ('SECONDARY' if h.get('secondary') else 'OTHER')
            except PyMongoError:result[n]='UNREACHABLE'
        return result
    def dispatch(self,q):
        action=q['action']
        if action=='status':return self.status()
        if action=='configure':
            cfg=self.client.admin.command('replSetGetConfig')['config']
            changed=False
            for m in cfg['members']:
                node=m['host'].split(':')[0]
                if m.get('tags',{}).get('node')!=node:
                    m.setdefault('tags',{})['node']=node;changed=True
            if changed:
                cfg['version']+=1;self.client.admin.command('replSetReconfig',cfg)
            return {'changed':changed,'config':cfg}
        if action=='versions':
            import platform,pymongo
            return {'mongodb':self.client.admin.command('buildInfo')['version'],
                    'python':platform.python_version(),'pymongo':pymongo.version,
                    'replica_config':self.client.admin.command('replSetGetConfig')['config']}
        if action=='phase':
            self.client.close();self.client=create_client(q['timeout_ms'],self.monitor)
            self.phase=q['phase'];self.runid=q['runid'];return {'roles':self.status()}
        if action=='trial':
            self.case(q['model'],q['index']);return self.trial
        if action=='barrier':
            key=q['key'];name='barriers'
            w,_,_=create_collections(self.client,name)
            w.replace_one({'_id':key},{'_id':key,'version':1},upsert=True)
            values=[]
            for c in self.direct:
                col=c[w.database.name][name].with_options(read_concern=ReadConcern('majority'),read_preference=Nearest())
                deadline=time.monotonic()+30
                while True:
                    d=col.find_one({'_id':key},max_time_ms=2000)
                    if d and d['version']==1:values.append(d);break
                    if time.monotonic()>deadline:raise RuntimeError('Barrier did not replicate')
                    time.sleep(.01)
            return values
        raise ValueError(action)
    def invoke(self,label,fn):
        self.trial['stage']=label;start=time.monotonic();offset=len(self.monitor.events)
        try:
            value=fn()
            events=self.monitor.events[offset:]
            stamp=next((e['operationTime'] for e in reversed(events) if e.get('operationTime')),None)
            self.trial['operations'].append({'stage':label,'ok':True,'elapsed_ms':(time.monotonic()-start)*1000,
                                            'value':value,'operationTime':stamp,'session_operation_time':self.session.operation_time})
            return value,stamp
        except PyMongoError as e:
            self.trial['operations'].append({'stage':label,'ok':False,'elapsed_ms':(time.monotonic()-start)*1000,
                                             'error':type(e).__name__,'message':str(e)})
            raise
    def write(self,col,doc,label):
        def fn():
            r=col.replace_one({'_id':doc['_id']},doc,upsert=True,session=self.session)
            return {'acknowledged':r.acknowledged,'matched_count':r.matched_count}
        return self.invoke(label,fn)[1]
    def read(self,col,key,label):
        return self.invoke(label,lambda:col.find_one({'_id':key},max_time_ms=2000,session=self.session))[0]
    def wait_value(self,col,key,value,label,timeout=5):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            doc=self.read(col,key,label)
            if doc and doc.get('version')==value:return doc
            time.sleep(.001)
        raise Inconclusive(label+' did not reach required value')
    def oplog(self,node,stamp,label,namespace,key):
        if stamp is None:raise Inconclusive('missing operation timestamp')
        doc=self.invoke(label,lambda:self.direct[node].local['oplog.rs'].find_one({'ts':stamp},max_time_ms=2000))[0]
        if not doc or doc.get('ns')!=namespace or doc.get('op') not in ('i','u'):
            raise Inconclusive('missing or mismatched oplog evidence')
        actual_id=doc.get('o2',doc.get('o',{})).get('_id')
        if actual_id!=key:raise Inconclusive('oplog document ID mismatch')
        return doc
    def case(self,model,index):
        self.monitor.events=[]
        self.session=causal_session(self.client)
        cid=f'{self.phase}-{model}-{index}'
        self.trial={'case':cid,'phase':self.phase,'model':model,'trial':index,
                    'outcome':'inconclusive','operations':[], 'session_id':self.session.session_id, 'causal_consistency':self.session.options.causal_consistency}
        name='r'+self.runid.replace('-','_')+'_'+model.lower()
        cols=create_collections(self.client,name)
        w,s1,s2=cols;x=cid+':x';y=cid+':y'
        old=3*index;first=old+1;second=old+2
        try:
            self.write(w,{'_id':x,'version':old},'baseline_write')
            # Preserve the original per-scenario baseline arrangement.
            if self.phase=='normal':
                self.wait_value(s1,x,old,'baseline_secondary1')
                if model=='MR':self.wait_value(s2,x,old,'baseline_secondary2')
            elif self.phase.startswith('node_') and model=='MR':
                self.wait_value(s2,x,old,'baseline_secondary2')
            t1=self.write(w,{'_id':x,'version':first},'W1')
            self.w,self.s1,self.s2=w,s1,s2
            self.x,self.y=x,y
            self.first,self.second,self.t1=first,second,t1
            from normal_config2_experiment import TESTS
            self.trial['outcome']=TESTS[model](self)
        except PyMongoError as e:
            self.trial.update(outcome='unavailable',error=type(e).__name__)
        except Inconclusive as e:
            self.trial.update(outcome='inconclusive',reason=str(e))
        finally:
            self.trial['events']=self.monitor.events
            self.session.end_session()

def docker_args(*args):
    executable=shutil.which('docker') or '/opt/homebrew/bin/docker'
    context=os.environ.get('LAB_DOCKER_CONTEXT')
    if not context and not os.environ.get('DOCKER_CONTEXT') and not os.environ.get('DOCKER_HOST'):
        if subprocess.run([executable,'context','inspect','colima-consistency-lab'],capture_output=True).returncode==0:
            context='colima-consistency-lab'
    return [executable]+(['--context',context] if context else [])+list(args)

def docker(*args):
    return subprocess.run(docker_args(*args),text=True,capture_output=True,check=True,timeout=120)

def compose_args(*args):
    executable=shutil.which('docker-compose') or '/opt/homebrew/bin/docker-compose'
    env=os.environ.copy()
    args0=docker_args()
    if '--context' in args0:env['DOCKER_CONTEXT']=args0[args0.index('--context')+1]
    return [executable,'-f',str(ROOT/'compose.yaml'),'-f',str(ROOT/'compose.config2.yaml')]+list(args),env

class Worker:
    def __init__(self):
        lookup,env=compose_args('ps','-q','client-config2')
        cid=subprocess.run(lookup,env=env,text=True,capture_output=True,check=True).stdout.strip()
        if not cid:raise RuntimeError('Start client-config2 before running experiments')
        for path in ROOT.glob('*config2*.py'):
            docker('cp',str(path),cid+':/lab/'+path.name)
        args,env=compose_args('exec','-T','client-config2','python','-u','config2_helpers.py','--worker')
        self.proc=subprocess.Popen(args,cwd=ROOT,env=env,text=True,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    def request(self,action,**kw):
        self.proc.stdin.write(json_util.dumps({'action':action,**kw})+'\n');self.proc.stdin.flush()
        with selectors.DefaultSelector() as s:
            s.register(self.proc.stdout,selectors.EVENT_READ)
            if not s.select(60):raise RuntimeError('Worker did not respond within 60 seconds')
        line=self.proc.stdout.readline()
        if not line:raise RuntimeError('Worker exited')
        reply=json_util.loads(line)
        if not reply['ok']:raise RuntimeError(reply['error'])
        return reply['value']
    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:self.proc.terminate();self.proc.wait(timeout=5)
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

def wait_roles(worker,expected,timeout=180):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        state=worker.request('status')
        if all(state[n]==v for n,v in expected.items()):return state
        time.sleep(.5)
    raise RuntimeError(f'Expected {expected}, observed {state}')

def project_network():
    networks=json.loads(docker('inspect','mongo3','--format','{{json .NetworkSettings.Networks}}').stdout)
    if len(networks)!=1:raise RuntimeError('Expected one MongoDB network')
    return next(iter(networks))

def recover(worker,log):
    net=project_network()
    attached=json.loads(docker('inspect','mongo1','--format','{{json .NetworkSettings.Networks}}').stdout)
    if net not in attached:docker('network','connect','--alias','mongo1',net,'mongo1')
    docker('start',*NODES)
    state=wait_roles(worker,HEALTHY)
    values=worker.request('barrier',key='recovery-'+uuid.uuid4().hex)
    log('recovery',roles=state,readbacks=values)
    return state

class Run:
    def __init__(self,scenario,trials,smoke=False,models=MODELS):
        self.lock=(ROOT/'.config2.lock').open('w');fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.started=datetime.now(timezone.utc).isoformat()
        self.id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+scenario+('-smoke-' if smoke else '-formal-')+uuid.uuid4().hex[:6]
        self.out=ROOT/'results_config2'/self.id;self.out.mkdir(parents=True)
        self.scenario=scenario;self.trials=trials;self.smoke=smoke;self.models=models
        files=sorted(set(ROOT.glob('*config2*.py'))|{ROOT/'config2.py',ROOT/'Dockerfile.config2',ROOT/'compose.config2.yaml',ROOT/'compose.yaml',ROOT/'config2_plan.md'})
        (self.out/'source').mkdir()
        for f in files:shutil.copy2(f,self.out/'source'/f.name)
        self.manifest={'database_name':DB_NAME,'started_at':self.started,'scenario':scenario,'trials_per_model_per_phase':trials,
                       'smoke':smoke,'models':list(models),'config':CONFIG,
                       'source_sha256':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}
        (self.out/'manifest.json').write_text(json.dumps(self.manifest,indent=2))
        self.file=(self.out/'history.jsonl').open('w');self.worker=Worker();self.summary=[]
    def log(self,kind,**data):
        self.file.write(json_util.dumps({'type':kind,'time':datetime.now(timezone.utc).isoformat(),**data})+'\n');self.file.flush()
    def phase(self,name):
        state=self.worker.request('phase',phase=name,runid=self.id,timeout_ms=30000 if name=='normal' else 500)['roles']
        if name in ('normal','node_after','partition_after'):assert state==HEALTHY
        self.log('phase_start',phase=name,roles=state)
        for model in self.models:
            counts=Counter()
            for i in range(self.trials):
                trial=self.worker.request('trial',model=model,index=i)
                self.log('trial',**trial);counts[trial['outcome']]+=1
                if (i+1)%50==0 or i+1==self.trials:print(name,model,f'{i+1}/{self.trials}',dict(counts),flush=True)
            self.summary.append({'phase':name,'model':model,'trials':self.trials,
                **{k:counts[k] for k in ('no_violation_observed','violation','unavailable','inconclusive')}})
            (self.out/'summary.json').write_text(json.dumps(self.summary,indent=2))
        self.log('phase_end',phase=name,roles=self.worker.request('status'))
    def finish(self,completed):
        try:
            recover(self.worker,self.log)
            for n in NODES:
                r=docker('logs','--since',self.started,n);(self.out/(n+'.log')).write_text(r.stdout+r.stderr)
            with (self.out/'summary.csv').open('w') as f:
                if self.summary:
                    w=csv.DictWriter(f,fieldnames=list(self.summary[0]));w.writeheader();w.writerows(self.summary)
            if completed:
                (self.out/'COMPLETE').write_text(datetime.now(timezone.utc).isoformat())
                if not self.smoke:
                    name={'normal':'normal_config2_results.json','node':'node_failure_config2_results.json','partition':'network_partition_config2_results.json','ryw':'test_ryw_config2_results.json'}[self.scenario]
                    (ROOT/name).write_text(json.dumps({'run_directory':str(self.out),'config':CONFIG,'results':self.summary},indent=2))
        finally:self.worker.close();self.file.close();self.lock.close()
        print('RESULT_DIRECTORY='+str(self.out),flush=True)

def run_scenario(scenario,default_trials,smoke=False,models=MODELS):
    run=Run(scenario,3 if smoke else default_trials,smoke,models)
    complete=False
    try:
        recover(run.worker,run.log)
        run.log('versions',value=run.worker.request('versions'))
        if scenario in ('normal','ryw'):run.phase('normal')
        elif scenario=='node':
            from node_failure_config2 import stop_node,start_node
            try:
                stop_node();state=wait_roles(run.worker,{'mongo1':'PRIMARY','mongo2':'UNREACHABLE','mongo3':'SECONDARY'},30)
                run.log('fault_start',fault='node_stop',roles=state,
                        state=json.loads(docker('inspect','mongo2','--format','{{json .State}}').stdout))
                run.phase('node_during')
            finally:recover(run.worker,run.log)
            time.sleep(2);run.phase('node_after')
        elif scenario=='partition':
            from network_partition_config2 import partition_node,wait_for_election
            try:
                net=partition_node();state=wait_for_election(run.worker)
                run.log('fault_start',fault='network_partition',network=net,roles=state)
                run.phase('partition_during')
            finally:recover(run.worker,run.log)
            time.sleep(2);run.phase('partition_after')
        complete=True
    finally:run.finish(complete)

def entry(scenario,n,models=MODELS):
    p=argparse.ArgumentParser();p.add_argument('--smoke',action='store_true');a=p.parse_args()
    run_scenario(scenario,n,a.smoke,models)

def worker_main():
    worker=DatabaseWorker()
    try:
        for line in sys.stdin:
            try:reply={'ok':True,'value':worker.dispatch(json_util.loads(line))}
            except Exception as e:
                import traceback
                reply={'ok':False,'error':traceback.format_exc()}
            print(json_util.dumps(reply),flush=True)
    finally:
        worker.client.close()
        for c in worker.direct:c.close()

if __name__=='__main__':
    if '--worker' in sys.argv:
        sys.modules['config2_helpers']=sys.modules[__name__]
        worker_main()
