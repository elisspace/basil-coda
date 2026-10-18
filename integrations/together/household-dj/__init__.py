"""Fixed DJ controls for the authorized household group; no arbitrary shell or file API."""
import json
import os
import pathlib
import subprocess
import sys
import time
from typing import Any

# Optional integration: an operator must explicitly bind its group before use.
# Never ship a personal Signal group identifier as an enabled default.
GROUP = os.environ.get('BASIL_SIGNAL_GROUP', '').strip()
WORK = pathlib.Path(os.environ.get('BASIL_STATE_DIR', str(pathlib.Path.home()/'.local/share/basil-coda/state'))).expanduser().resolve()
ENGINE = pathlib.Path(os.environ.get('BASIL_ENGINE_DIR', str(pathlib.Path(__file__).resolve().parents[3]/'engine'))).expanduser().resolve()
TRANSPORT={'skip':'next','pause':'pause','resume':'play'}
ACTIONS=('status','skip','pause','resume','stop','stop_management','feedback','start')

def partners():
    if not GROUP.startswith('group:'):
        return set()
    try:
        settings=json.loads((pathlib.Path(__file__).parent.parent/'together-signal'/'settings.json').read_text())
        if not isinstance(settings, dict) or settings.get('target_chat_id') != GROUP:
            return set()
        identities=settings.get('identities', {})
        if not isinstance(identities, dict):
            return set()
        return {identity for values in identities.values() if isinstance(values, list)
                for identity in values if isinstance(identity, str) and identity}
    except (OSError, ValueError, TypeError):
        return set()

def allowed(profile,source):
    if not GROUP.startswith('group:'):
        return False
    if not (profile=='together' and source.get('profile')=='together' and source.get('platform')=='signal' and source.get('chat_id')==GROUP):return False
    return bool({source.get('user_id'),source.get('user_id_alt')} & partners())

def run(script,*args) -> Any:
    if script not in {'djctl.py', 'dj_session.py'}:
        raise ValueError('Unsupported helper')
    result=subprocess.run([sys.executable,str(ENGINE/script),*args],cwd=WORK,text=True,capture_output=True,timeout=45,shell=False)
    if result.returncode: raise RuntimeError('DJ helper did not confirm success; do not retry an uncertain change automatically.')
    return json.loads(result.stdout) if result.stdout.strip().startswith(('{','[')) else {'receipt':result.stdout.strip()}

def management():
    result=subprocess.run(['systemctl','--user','is-active','hermes-dj-session'],capture_output=True,text=True,timeout=5,shell=False)
    return result.stdout.strip()=='active'

def update_brief(brief):
    # Write only the explicitly shared session brief, never private profile memories.
    import fcntl
    with (WORK/'control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state=json.loads((WORK/'session.json').read_text())
        state['brief']=brief
        tmp=WORK/'session.household.tmp';tmp.write_text(json.dumps(state,indent=2));tmp.replace(WORK/'session.json')
        actual=json.loads((WORK/'session.json').read_text())
        if actual.get('brief')!=brief:raise RuntimeError('Brief update not verified')
    return {'brief':brief,'active':bool(state.get('active') is True and state.get('management_version') == 2),'queued_tracks_unchanged':True}

def dispatch(args):
    if not isinstance(args,dict) or set(args)-{'action','brief'}:return {'ok':False,'error':'Unsupported fields'}
    action=args.get('action')
    if action not in ACTIONS:return {'ok':False,'error':'Unsupported DJ action'}
    brief=args.get('brief')
    if action in ('feedback','start'):
        if not isinstance(brief,str) or not 1<=len(brief.strip())<=1500:return {'ok':False,'error':'A musical brief of 1–1500 characters is required'}
        brief=brief.strip()
    elif brief is not None:return {'ok':False,'error':'brief is only accepted for feedback or start'}
    result: dict = {}
    try:
        if action=='status':
            player=run('djctl.py','status');song=player.get('api_snapshot') or {}
            result={'song':{k:song.get(k) for k in ('title','artist','videoId')},'live':player.get('live'),'session':run('dj_session.py','status'),'worker_running':management(),'queue':run('djctl.py','queue')}
        elif action in TRANSPORT:result=run('djctl.py',TRANSPORT[action])
        elif action in ('stop','stop_management'):
            run('dj_session.py','stop')
            if management():raise RuntimeError('DJ management stop not confirmed')
            result={'management_stopped':True}
            if action=='stop':result['player']=run('djctl.py','pause')
        elif action=='feedback':result=update_brief(brief)
        else:
            # Preserve the existing queue. No queue-clearing or library authority is exposed.
            queue=run('djctl.py','queue')
            if not queue:return {'ok':False,'error':'Player queue is empty. Seed a discovery session from the private DJ chat first; no playback was started.'}
            if management():
                result=update_brief(brief)
            else:
                state=run('dj_session.py','status')
                if state.get('active'):run('dj_session.py','stop')
                run('dj_session.py','start','--brief',brief)
                if not management():raise RuntimeError('Worker start not confirmed')
                result={'session':run('dj_session.py','status'),'queued_tracks_unchanged':True}
            result['playback_unchanged']=True
        return {'ok':True,'result':result}
    except (OSError,subprocess.TimeoutExpired,ValueError,RuntimeError):
        return {'ok':False,'error':'DJ operation was not confirmed. Player may be unavailable; for a change, outcome may be uncertain. Check status rather than blindly retrying.'}

SCHEMA={'name':'household_dj','description':'Control the explicitly bound household player using fixed status/skip/pause/resume/stop/start/feedback actions. No shell, credentials, queue edits, library or saved-playlist changes. Feedback changes future discovery choices, not already queued tracks. Start enables management until OFF, preserves the existing queue and never starts/resumes audio; an empty queue requires private DJ setup.','parameters':{'type':'object','properties':{'action':{'type':'string','enum':list(ACTIONS)},'brief':{'type':'string','maxLength':1500,'description':'Musical direction only, required for start or feedback; absent for other actions.'}},'required':['action'],'additionalProperties':False}}

def register(ctx):
    registered=ctx.profile_name
    def handler(args,**kwargs):
        from gateway.session_context import get_session_env
        source={k:get_session_env('HERMES_SESSION_'+k.upper(),'') for k in ('platform','profile','chat_id','user_id','user_id_alt')}
        result=dispatch(args) if ctx.profile_name==registered and allowed(registered,source) else {'ok':False,'error':'DJ control is only available in the authorized household group.'}
        return json.dumps(result,ensure_ascii=False)
    ctx.register_tool(name='household_dj',toolset='household_dj',schema=SCHEMA,handler=handler,description=SCHEMA['description'])
