"""Exercise scope recovery, single-flight ownership and admitted queued delivery."""
import fcntl
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('monitor_workflow', HERE / 'monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)
goals = []


def goal(name, passed):
    goals.append({'goal': name, 'verdict': 'PASS' if passed else 'FAIL'})


with tempfile.TemporaryDirectory(prefix='fleet-bridge-workflow-') as tmp:
    home = Path(tmp)
    scope = home / 'scopes'
    scope.mkdir()
    state = home / 'state'
    state.mkdir()
    database = home / 'bb.db'
    db = sqlite3.connect(database)
    db.execute('CREATE TABLE threads(id TEXT,parent_thread_id TEXT,status TEXT,provider_id TEXT,environment_id TEXT,archived_at INTEGER,deleted_at INTEGER)')
    db.execute('CREATE TABLE events(id TEXT,thread_id TEXT,type TEXT,sequence INTEGER,provider_thread_id TEXT)')
    for ident in ['thr_fixture', 'thr_sibling']:
        db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?)', (ident, None, 'idle', 'codex', 'env_' + ident, None, None))
    for ident, kind, sequence in [('requested', 'client/turn/requested', 1), ('started', 'turn/started', 2), ('completed', 'turn/completed', 3)]:
        db.execute('INSERT INTO events VALUES(?,?,?,?,?)', ('evt_' + ident, 'thr_fixture', kind, sequence, '117471a8-1970-4376-8672-9de66c418579'))
    db.commit()
    db.close()
    idle_unknown = [{'thread': 'thr_child', 'status': 'idle', 'hold': 'SCOPE_UNKNOWN'}]
    open_goal = [{'id': 'P1', 'status': 'open'}]
    goal('Idle children with missing local receipts can wake their existing coordinator', monitor.reconciliation_needed('idle', open_goal, [], [], idle_unknown))
    goal('A queued child prevents a duplicate coordinator wake', not monitor.reconciliation_needed('idle', open_goal, [], [], [{'status': 'idle', 'hold': 'QUEUED'}]))
    goal('A running child prevents coordinator recovery dispatch', not monitor.reconciliation_needed('idle', open_goal, [], [], [{'status': 'active', 'hold': 'RUNNING'}]))
    goal('An owner permission hold cannot become a recovery wake', not monitor.reconciliation_needed('idle', [{'id': 'P1', 'status': 'blocked-on-user'}], [], [], idle_unknown))
    config = {'schemaVersion': 1, 'stateRoot': str(state), 'bbDatabase': str(database), 'scopeRoot': str(scope),
              'jobsRoot': str(home / 'jobs'), 'lockFile': str(home / 'shared.lock'),
              'targets': [{'thread': ident, 'purposes': ['P1'], 'project': ident,
                           'workspace': 'ws_fixture', 'node': 'node_fixture',
                           'providerJournalRoot': str(home / 'journals')} for ident in ['thr_fixture', 'thr_sibling']],
              'scheduler': {'label': 'local.agent-config-kit.fleet.fixture', 'intervalSeconds': 300}}
    config_path = home / 'config.json'
    config_path.write_text(json.dumps(config))
    monitor.configure(config_path)
    calls = []

    def fake_bb(args):
        calls.append(args)
        if args[:3] == ['thread', 'queue', 'list']:
            return []
        if args[:2] == ['thread', 'show']:
            return {'thread': {'id': args[2], 'status': 'idle', 'providerId': 'codex'}, 'environment': {'id': 'env_' + args[2]}}
        if args[:2] == ['fleet', 'route']:
            return {'routable': True, 'providerId': 'codex'}
        if args[:2] == ['thread', 'tell']:
            assert '--mode' in args and args[args.index('--mode') + 1] == 'queue'
            return {'delivery': 'queued'}
        raise AssertionError('Unexpected action: ' + repr(args))

    real_run = subprocess.run

    def fake_process(argv, **kwargs):
        if argv[:3] == ['elyra', 'chat', 'list']:
            return subprocess.CompletedProcess(argv, 0, stdout='{"ok":true,"result":{"chats":[]}}')
        if len(argv) > 1 and argv[1] == str(monitor.INPUT_GUARD):
            return real_run(argv, **kwargs)
        raise AssertionError('Unexpected process: ' + repr(argv))

    original = {'id': 'P1', 'status': 'done', 'evidence': ['accepted original goal']}
    ledger = scope / 'thr_fixture.json'
    (scope / 'thr_sibling.json').write_text(json.dumps({'purposes': [original]}))
    polls = []
    with patch.object(monitor, 'bb', side_effect=fake_bb), patch.object(monitor.subprocess, 'run', side_effect=fake_process), patch.object(monitor, 'native_review_state', return_value={'state': 'IDLE', 'pending': []}):
        def poll(mutate=False):
            result = monitor.run(mutate=mutate)['targets']
            row = result['thr_fixture']
            polls.append({'state': row['state'], 'tracked': row['trackedPurposeIds'], 'sibling': result['thr_sibling']['state']})
            return row

        ledger.write_text(json.dumps({'purposes': [original, {'id': 'P2', 'status': 'open'}]}))
        poll()
        ledger.unlink()
        poll()
        ledger.write_text(json.dumps({'purposes': [original, {'id': 'P2', 'status': 'done', 'evidence': []}]}))
        poll()
        ledger.write_text(json.dumps({'purposes': [original, {'id': 'P2', 'status': 'done', 'evidence': ['accepted followup']}]}))
        poll()
        ledger.write_text('{"purposes":')
        poll()
        ledger.write_text(json.dumps({'purposes': [original, {'id': 'P2', 'status': 'done', 'evidence': ['accepted followup']}]}))
        poll(mutate=True)
        goal('Open followup is tracked', polls[0]['state'] == 'RUNNABLE_IDLE' and 'P2' in polls[0]['tracked'])
        goal('Missing scope retains the followup', polls[1]['state'] == 'UNKNOWN' and 'P2' in polls[1]['tracked'])
        goal('Missing acceptance evidence cannot close the followup', polls[2]['state'] != 'COMPLETE')
        goal('Acceptance evidence closes settled work', polls[3]['state'] == 'COMPLETE')
        goal('Corrupt scope leaves the sibling observable', polls[4]['state'] == 'UNKNOWN' and polls[4]['sibling'] == 'COMPLETE')
        goal('Repaired scope resumes completion', polls[5]['state'] == 'COMPLETE' and (state / 'finished.json').exists())
        with (home / 'shared.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = len(calls)
            held = monitor.run(mutate=True)
            goal('A second scheduler cannot dispatch while the shared lock is held', held['status'] == 'SINGLE_FLIGHT_HELD' and len(calls) == before)
        child_db = sqlite3.connect(database)
        child_db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?)', ('thr_child', 'thr_fixture', 'idle', 'codex', 'env_child', None, None))
        child_db.commit()
        child_db.close()
        ledger.write_text(json.dumps({'purposes': [original, {'id': 'P2', 'status': 'open'}]}))
        row = poll(mutate=True)
        goal('A new round reopens after a finished round', not (state / 'finished.json').exists())
        goal('An idle completed owner uses actual metadata admission and queued delivery', row.get('inputAdmission', {}).get('admitted') and row.get('nudgeReceipt', {}).get('delivery') == 'queued')
        goal('The real workflow reconciles an idle child with a missing local scope', row['sourceChildWorkHolds'][0]['hold'] == 'SCOPE_UNKNOWN' and bool(row.get('nudgeReceipt')))
        before = sum(args[:2] == ['thread', 'tell'] for args in calls)
        poll(mutate=True)
        goal('An immediate repeat does not duplicate the queued nudge', sum(args[:2] == ['thread', 'tell'] for args in calls) == before)
        child_db = sqlite3.connect(database)
        child_db.execute('DELETE FROM threads WHERE id=?', ('thr_child',))
        child_db.commit()
        child_db.close()
        closed_followup = {'id': 'P2', 'status': 'done', 'evidence': ['accepted followup']}
        late = {'id': 'P3', 'status': 'done', 'evidence': []}
        ledger.write_text(json.dumps({'purposes': [original, closed_followup, late]}))
        row = poll()
        goal('A goal added and completed between polls remains required without evidence', 'P3' in row['trackedPurposeIds'] and row['state'] != 'COMPLETE')
        late['evidence'] = ['accepted late followup']
        ledger.write_text(json.dumps({'purposes': [original, closed_followup, late]}))
        row = poll()
        goal('An evidenced between-poll goal remains tracked when completion is allowed', 'P3' in row['trackedPurposeIds'] and row['state'] == 'COMPLETE')
        original['status_marked_at'] = '2026-01-01T00:00:00Z'
        revision = {'quote': 'Accepted additional owner outcome', 'accepted_at': '2026-01-02T00:00:00Z'}
        ledger.write_text(json.dumps({'purposes': [original, closed_followup, late], 'accepted_revisions': [revision]}))
        row = poll()
        goal('A revision newer than original closure cannot silently close', row['state'] == 'SCOPE_REVISION_PENDING' and len(row['pendingAcceptedRevisions']) == 1)
        revision.update({'status': 'done', 'evidence': ['source owner outcome receipt']})
        ledger.write_text(json.dumps({'purposes': [original, closed_followup, late], 'accepted_revisions': [revision]}))
        row = poll()
        goal('An explicit evidenced revision receipt permits closure', row['state'] == 'COMPLETE' and not row['pendingAcceptedRevisions'])
        older = {'quote': 'Earlier accepted original scope', 'accepted_at': '2025-12-31T00:00:00Z'}
        ledger.write_text(json.dumps({'purposes': [original, closed_followup, late], 'accepted_revisions': [older]}))
        row = poll()
        goal('Original evidenced acceptance preserves older completed revision history', row['state'] == 'COMPLETE' and not row['pendingAcceptedRevisions'])
        ledger.write_text(json.dumps({'purposes': None, 'accepted_revisions': []}))
        row = poll()
        goal('Malformed revision/purpose metadata fails closed without losing the sibling', row['state'] == 'UNKNOWN' and polls[-1]['sibling'] == 'COMPLETE')
    db = sqlite3.connect(database)
    db.execute('UPDATE threads SET status=? WHERE id=?', ('active', 'thr_sibling'))
    db.execute('UPDATE threads SET environment_id=? WHERE id=?', ('env_thr_fixture', 'thr_sibling'))
    db.commit()
    admitted = monitor.queue_admission(db, {'id': 'thr_fixture', 'status': 'idle'}, {'id': 'env_thr_fixture'})
    goal('A different active write owner blocks admission', not admitted['admitted'])
    db.close()

packet = {'persona': 'Fleet operator', 'target': {'stack': 'Portable monitor and real metadata guard with disposable BB/provider fixtures',
          'monitorSha256': hashlib.sha256((HERE / 'monitor.py').read_bytes()).hexdigest()}, 'polls': polls,
          'goals': goals, 'verdict': 'PASS' if all(g['verdict'] == 'PASS' for g in goals) else 'FAIL'}
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(json.dumps(packet, indent=2) + '\n')
print(json.dumps(packet, indent=2))
raise SystemExit(0 if packet['verdict'] == 'PASS' else 1)
