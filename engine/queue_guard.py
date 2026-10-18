#!/usr/bin/env python3
"""Explicitly armed generation-scoped queue guard. No model/transport/account calls."""
import argparse
import json
import pathlib
import re
import subprocess
import time
from djctl import SOURCE, live_status, append_queue_snapshot, require_queue_ready
import dj_session as session


def queue_ids(rows):
    values = [r['videoId'] for r in rows]
    if len(values)>512 or len(set(values))!=len(values) or not all(re.fullmatch(r'[A-Za-z0-9_-]{11}',v) for v in values):
        raise ValueError('Queue guard needs a bounded unambiguous exact queue')
    if sum(r.get('selected') is True for r in rows)!=1:
        raise ValueError('Queue selection unknown')
    return values


def check():
    # OFF shares this lock and drains the existing append_deadline_ms renderer
    # lease. There is no asynchronous destructive observer or second scheduler.
    with session.control_lock():
        state = session.load()
        if not session.enabled(state): return {'skipped':'OFF'}
        policy = state.get('queue_guard', {})
        if policy.get('version')!=1 or policy.get('generation')!=state.get('generation'):
            return {'skipped':'not armed for this generation'}
        require_queue_ready()
        if live_status().get('paused') is not False: return {'skipped':'paused/unknown'}
        before = append_queue_snapshot(); expected = queue_ids(before)
        selected = next(r['videoId'] for r in before if r.get('selected'))
        deadline = int(time.time()*1000)+8000
        state['append_deadline_ms'] = deadline
        session.save(state)
        output = subprocess.check_output(['node',str(SOURCE/'player_dom.mjs'),'queue-guard',state['generation'],json.dumps(expected),str(deadline)],text=True,timeout=15)
        result = json.loads(output)
        after = append_queue_snapshot(); actual = queue_ids(after)
        removed = result.get('removedIds')
        if (result.get('generation')!=state['generation'] or result.get('beforeIds')!=expected or
            result.get('afterIds')!=actual or not isinstance(removed,list) or len(removed)>100 or
            len(set(removed))!=len(removed) or any(v not in expected for v in removed) or
            actual!=[v for v in expected if v not in removed] or
            next(r['videoId'] for r in after if r.get('selected'))!=selected):
            raise ValueError('Queue guard readback uncertain; inspect without retrying')
        baseline = policy.get('verified_ids',[])
        # Existing rows, including unknown/library/history/manual rows, are never
        # deletion candidates. A mismatch is a review signal, not ownership proof.
        if actual!=baseline:
            result['warning']='unexplained queue change; review manual additions/history/server replacement, never infer recommendations'
        if result.get('blocked'):
            result['warning']=result.get('warning',result['blocked'])
        policy['observed_ids']=actual
        policy['last_result']=result
        policy['last_check']=time.time()
        if not result.get('warning'): policy['verified_ids']=actual
        state['queue_guard']=policy
        session.save(state)
        return result


def arm(checkpoint):
    """Explicit human-reviewed compact djctl queue JSON; exact readback required."""
    rows=json.loads(pathlib.Path(checkpoint).read_text())
    expected=queue_ids(rows)
    with session.control_lock():
        state=session.load()
        if not session.enabled(state): raise ValueError('DJ OFF; cannot arm guard')
        require_queue_ready()
        if queue_ids(append_queue_snapshot())!=expected: raise ValueError('Checkpoint is stale; inspect current queue')
        state['queue_guard']={'version':1,'generation':state['generation'],'verified_ids':expected}
        session.save(state)
    return {'armed':True,'generation':state['generation'],'verified_ids':expected}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['arm','check','disarm'])
    p.add_argument('--checkpoint',type=pathlib.Path)
    args=p.parse_args()
    if args.command=='arm':
        if args.checkpoint is None:p.error('arm requires a reviewed --checkpoint compact queue JSON')
        result=arm(args.checkpoint)
    elif args.command=='disarm':
        with session.control_lock():
            state=session.load();state.pop('queue_guard',None);session.save(state)
        result={'armed':False}
    else:result=check()
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
