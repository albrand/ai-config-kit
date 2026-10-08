"""Exercise scope recovery, single-flight ownership and admitted queued delivery."""
import fcntl
import argparse
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import shutil
import io
import plistlib
import os
import stat
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('monitor_workflow', HERE / 'monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', nargs='?', type=Path)
parser.add_argument('--input-guard', type=Path, help='Actual installed/staged metadata-guard prerequisite for this isolated fixture')
args = parser.parse_args()
if args.input_guard:
    monitor.INPUT_GUARD = args.input_guard.resolve(strict=True)
goals = []


def goal(name, passed):
    goals.append({'goal': name, 'verdict': 'PASS' if passed else 'FAIL'})


with tempfile.TemporaryDirectory(prefix='fleet-bridge-workflow-') as tmp:
    home = Path(tmp)
    scope = home / 'scopes'
    scope.mkdir()
    state = home / 'state'
    state.mkdir(mode=0o700)
    database = home / 'bb.db'
    db = sqlite3.connect(database)
    db.execute('CREATE TABLE threads(id TEXT,parent_thread_id TEXT,status TEXT,provider_id TEXT,environment_id TEXT,archived_at INTEGER,deleted_at INTEGER)')
    db.execute('CREATE TABLE events(id TEXT,thread_id TEXT,type TEXT,sequence INTEGER,provider_thread_id TEXT,data TEXT,turn_id TEXT)')
    for ident in ['thr_fixture', 'thr_sibling']:
        db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?)', (ident, None, 'idle', 'codex', 'env_' + ident, None, None))
    for ident, kind, sequence in [('requested', 'client/turn/requested', 1), ('started', 'turn/started', 2), ('completed', 'turn/completed', 3)]:
        db.execute('INSERT INTO events(id,thread_id,type,sequence,provider_thread_id) VALUES(?,?,?,?,?)', ('evt_' + ident, 'thr_fixture', kind, sequence, '117471a8-1970-4376-8672-9de66c418579'))
    db.execute('UPDATE events SET turn_id=?', ('fixture-turn-1',))
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
    original_umask = os.umask(0o022)
    state.chmod(0o755)
    try:
        try:
            monitor.run(mutate=True)
            rejected = False
        except ValueError:
            rejected = True
        goal('A permissive pre-existing state root is rejected before task text or a brief is written',
             rejected and not (state / 'monitor-state.json').exists() and not list(state.glob('*brief*')))
        state.chmod(0o700)
        existing_brief = state / 'privacy-existing-brief.md'
        existing_brief.write_text('old task text')
        existing_brief.chmod(0o644)
        monitor.private_text(existing_brief, 'updated private task text')
        goal('Replacing an existing permissive brief makes the new bytes private under umask 022',
             stat.S_IMODE(existing_brief.stat().st_mode) == 0o600 and existing_brief.read_text() == 'updated private task text')
        existing_json = state / 'privacy-existing-record.json'
        existing_json.write_text('{"old":true}')
        existing_json.chmod(0o644)
        monitor.save(existing_json, {'private': 'new task receipt'})
        goal('Replacing a permissive JSON record produces 0600 task data under umask 022',
             stat.S_IMODE(existing_json.stat().st_mode) == 0o600 and json.loads(existing_json.read_text()) == {'private': 'new task receipt'})
        actual_stat = Path.stat

        def foreign_owner(path, *stat_args, **stat_kwargs):
            measured = actual_stat(path, *stat_args, **stat_kwargs)
            if path == state:
                values = list(measured)
                values[4] = os.getuid() + 1
                return os.stat_result(values)
            return measured

        before_files = sorted(p.name for p in state.iterdir())
        with patch.object(Path, 'stat', foreign_owner):
            try:
                monitor.run(mutate=True)
                rejected = False
            except ValueError:
                rejected = True
        goal('A foreign filesystem owner is rejected before task reads or new writes',
             rejected and sorted(p.name for p in state.iterdir()) == before_files and not (state / 'monitor-state.json').exists())
    finally:
        os.umask(original_umask)
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
        # Independent later interleavings start without the successful fixture
        # round's delivery history; this is only our disposable temp directory.
        shutil.rmtree(state / 'deliveries')
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
        prior = json.loads((state / 'monitor-state.json').read_text())
        prior['targets']['thr_fixture'].pop('knownPurposeIds')
        (state / 'monitor-state.json').write_text(json.dumps(prior))
        upgrade_goal = {'id': 'P4', 'status': 'done', 'evidence': []}
        ledger.write_text(json.dumps({'purposes': [original, closed_followup, late, upgrade_goal]}))
        row = poll()
        goal('Legacy-state upgrade cannot bless an untracked closed goal without evidence', 'P4' in row['trackedPurposeIds'] and row['state'] != 'COMPLETE')
        upgrade_goal['evidence'] = ['accepted upgraded goal']
        ledger.write_text(json.dumps({'purposes': [original, closed_followup, late, upgrade_goal]}))
        row = poll()
        goal('A legacy-upgrade goal stays tracked after its evidence arrives', 'P4' in row['trackedPurposeIds'] and row['state'] == 'COMPLETE')
        base = json.loads((state / 'monitor-state.json').read_text())
        baseline_fixture = {p.name: p.read_bytes() for p in (state / 'scope-baselines').glob('*.json')}

        def restore_snapshot(value):
            # Reset both independent copies to the same controlled pre-case
            # state. Production never discards a durable baseline this way.
            for p in (state / 'scope-baselines').glob('*.json'):
                p.unlink()
            for name, raw in baseline_fixture.items():
                (state / 'scope-baselines' / name).write_bytes(raw)
            (state / 'monitor-state.json').write_text(json.dumps(value))
        malformed_results = []
        newer = {'id': 'P5', 'status': 'done', 'evidence': []}
        for malformed in [None, 'P1', {'P1': True}, ['P1', None], ['P1', 'P1'], [], ['other']]:
            prior = json.loads(json.dumps(base))
            prior['targets']['thr_fixture']['knownPurposeIds'] = malformed
            restore_snapshot(prior)
            ledger.write_text(json.dumps({'purposes': [original, closed_followup, late, upgrade_goal, newer]}))
            row = poll()
            malformed_results.append(row['state'] != 'COMPLETE' and 'P5' in row['trackedPurposeIds'])
        goal('Explicit null baseline cannot bless an untracked closed goal', malformed_results[0])
        goal('Every malformed baseline shape conservatively retains the new goal', all(malformed_results))
        prior = json.loads(json.dumps(base))
        prior['targets']['thr_fixture']['trackedPurposeIds'] = None
        restore_snapshot(prior)
        row = poll()
        goal('Malformed tracked scope reports unknown without stopping the sibling', row['state'] == 'UNKNOWN' and polls[-1]['sibling'] == 'COMPLETE')
        malformed_target_results = []
        for malformed in [None, 'bad', [], 1, False]:
            prior = json.loads(json.dumps(base))
            prior['targets']['thr_fixture'] = malformed
            restore_snapshot(prior)
            row = poll()
            malformed_target_results.append(row['state'] == 'UNKNOWN' and polls[-1]['sibling'] == 'COMPLETE')
        goal('Malformed persisted target records leave the valid sibling observable', all(malformed_target_results))
        malformed_container_results = []
        for malformed in [None, 'bad', [], 1, False]:
            restore_snapshot({'targets': malformed})
            row = poll()
            malformed_container_results.append(row['state'] == 'UNKNOWN' and polls[-1]['sibling'] == 'UNKNOWN')
        goal('Malformed target containers still observe both targets without inventing a baseline', all(malformed_container_results))
        (state / 'monitor-state.json').write_text('{"targets":')
        row = poll()
        goal('Corrupt persisted JSON reports both targets as unknown', row['state'] == 'UNKNOWN' and polls[-1]['sibling'] == 'UNKNOWN')
        restore_snapshot(base)
        malformed_evidence = ['not an evidence list', {'note': 'not a list'}, True, [''], [{}], [{'note': 1}], [{'note': 'proof', 'at': False}]]
        purpose_results = []
        revision_results = []
        for malformed in malformed_evidence:
            broken_original = dict(original, evidence=malformed)
            ledger.write_text(json.dumps({'purposes': [broken_original, closed_followup, late, upgrade_goal]}))
            row = poll()
            purpose_results.append(row['state'] != 'COMPLETE')
            broken_revision = {'quote': 'Accepted additional outcome', 'accepted_at': '2026-01-02T00:00:00Z', 'status': 'done', 'evidence': malformed}
            ledger.write_text(json.dumps({'purposes': [original, closed_followup, late, upgrade_goal], 'accepted_revisions': [broken_revision]}))
            row = poll()
            revision_results.append(row['state'] == 'UNKNOWN')
        goal('Malformed truthy purpose evidence cannot complete the workflow', all(purpose_results))
        goal('Malformed truthy revision evidence cannot complete the workflow', all(revision_results))
        noted = dict(original, evidence=[{'note': 'source owner acceptance', 'at': '2026-01-03T00:00:00Z'}])
        ledger.write_text(json.dumps({'purposes': [noted, closed_followup, late, upgrade_goal]}))
        row = poll()
        goal('Structured source-owner evidence remains compatible', row['state'] == 'COMPLETE')
        child_db = sqlite3.connect(database)
        child_db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?)', ('thr_bad_child', 'thr_fixture', 'idle', 'codex', 'env_child', None, None))
        child_db.commit()
        child_db.close()
        child_ledger = scope / 'thr_bad_child.json'
        malformed_children = [[{'status': 'done', 'evidence': ['proof']}], [{'id': '', 'status': 'done', 'evidence': ['proof']}],
                              [{'id': None, 'status': 'done', 'evidence': ['proof']}], [],
                              [{'id': 'P1', 'status': 'done', 'evidence': ['proof']}, {'id': 'P1', 'status': 'done', 'evidence': ['proof']}],
                              [{'id': 'P1', 'status': 'done', 'evidence': 'scalar'}]]
        child_results = []
        for malformed in malformed_children:
            child_ledger.write_text(json.dumps({'purposes': malformed}))
            row = poll()
            child_results.append(row['state'] != 'COMPLETE' and row['sourceChildWorkHolds'][0]['hold'] == 'SCOPE_UNKNOWN')
        goal('A child purpose without an ID cannot settle or close its parent', child_results[0])
        goal('Malformed child purpose/evidence records all preserve the parent hold', all(child_results))
        child_ledger.write_text(json.dumps({'purposes': [{'id': 'P1', 'status': 'done', 'evidence': ['accepted child goal']}]}))
        row = poll()
        goal('A properly evidenced child purpose can settle its parent', row['state'] == 'COMPLETE')
        ledger.write_text(json.dumps({'purposes': None, 'accepted_revisions': []}))
        row = poll()
        goal('Malformed revision/purpose metadata fails closed without losing the sibling', row['state'] == 'UNKNOWN' and polls[-1]['sibling'] == 'COMPLETE')
        ledger.write_text(json.dumps({'purposes': [{'id': 'P1', 'status': 'open'}, closed_followup, late, upgrade_goal]}))
        snapshot = json.loads((state / 'monitor-state.json').read_text())
        snapshot['targets']['thr_fixture']['nudges'] = 0
        snapshot['targets']['thr_fixture']['lastNudgeAt'] = 0
        real_admission = monitor.queue_admission

        def competing_owner_after_admission(connection, thread, environment):
            admitted = real_admission(connection, thread, environment)
            assert admitted['admitted']
            other = sqlite3.connect(database)
            other.execute('UPDATE threads SET status=?,environment_id=? WHERE id=?', ('active', 'env_thr_fixture', 'thr_sibling'))
            other.commit()
            other.close()
            return admitted

        restore_snapshot(snapshot)
        before = sum(args[:2] == ['thread', 'tell'] for args in calls)
        with patch.object(monitor, 'queue_admission', side_effect=competing_owner_after_admission):
            row = poll(mutate=True)
        goal('A competing owner appearing after admission blocks delivery with no queued message',
             row.get('inputAdmission', {}).get('admitted') and not row.get('nudgeReceipt') and
             sum(args[:2] == ['thread', 'tell'] for args in calls) == before)
        other = sqlite3.connect(database)
        other.execute('UPDATE threads SET status=?,environment_id=? WHERE id=?', ('idle', 'env_thr_sibling', 'thr_sibling'))
        other.commit()
        other.close()

        def changed_lease_after_admission(connection, thread, environment):
            admitted = real_admission(connection, thread, environment)
            assert admitted['admitted']
            other = sqlite3.connect(database)
            for suffix, kind, sequence in [('requested2', 'client/turn/requested', 4), ('started2', 'turn/started', 5), ('completed2', 'turn/completed', 6)]:
                other.execute('INSERT INTO events(id,thread_id,type,sequence,provider_thread_id,turn_id) VALUES(?,?,?,?,?,?)', ('evt_' + suffix, 'thr_fixture', kind, sequence, '117471a8-1970-4376-8672-9de66c418579', 'fixture-turn-' + str((sequence - 1) // 3 + 1)))
            other.commit()
            other.close()
            return admitted

        restore_snapshot(snapshot)
        with patch.object(monitor, 'queue_admission', side_effect=changed_lease_after_admission):
            row = poll(mutate=True)
        goal('A newer completed adapter turn cannot receive input admitted for the previous lease',
             row.get('inputAdmission', {}).get('admitted') and not row.get('nudgeReceipt') and
             sum(args[:2] == ['thread', 'tell'] for args in calls) == before)
        other = sqlite3.connect(database)
        other.execute('INSERT INTO events(id,thread_id,type,sequence,provider_thread_id,turn_id) VALUES(?,?,?,?,?,?)', ('evt_requested3', 'thr_fixture', 'client/turn/requested', 7, '117471a8-1970-4376-8672-9de66c418579', 'fixture-turn-3'))
        other.commit()
        other.close()
        restore_snapshot(snapshot)
        row = poll(mutate=True)
        goal('A new unstarted request after completion blocks admission and enqueue despite idle status and empty queue',
             not row.get('inputAdmission', {}).get('admitted') and not row.get('nudgeReceipt') and
             sum(args[:2] == ['thread', 'tell'] for args in calls) == before)
        other = sqlite3.connect(database)
        for suffix, kind, sequence in [('started3', 'turn/started', 8), ('completed3', 'turn/completed', 9)]:
            other.execute('INSERT INTO events(id,thread_id,type,sequence,provider_thread_id,turn_id) VALUES(?,?,?,?,?,?)', ('evt_' + suffix, 'thr_fixture', kind, sequence, '117471a8-1970-4376-8672-9de66c418579', 'fixture-turn-3'))
        other.commit()
        other.close()
        restore_snapshot(snapshot)
        row = poll(mutate=True)
        goal('Only a request followed by its start and completion can admit queued recovery',
             row.get('inputAdmission', {}).get('admitted') and row.get('nudgeReceipt', {}).get('delivery') == 'queued' and
             sum(args[:2] == ['thread', 'tell'] for args in calls) == before + 1)
        prepared_before_call = []
        accepted = []

        def accepted_then_timeout(args):
            result = fake_bb(args)
            if args[:2] == ['thread', 'tell']:
                intents = [json.loads(p.read_text()) for p in (state / 'deliveries/thr_fixture').glob('*.json')]
                prepared_before_call.append(any(p['status'] == 'prepared' and p['attempt'] == 2 for p in intents))
                accepted.append(args[2])
                other = sqlite3.connect(database)
                for suffix, kind, sequence in [('requested4', 'client/turn/requested', 10), ('started4', 'turn/started', 11), ('completed4', 'turn/completed', 12)]:
                    other.execute('INSERT INTO events(id,thread_id,type,sequence,provider_thread_id,turn_id) VALUES(?,?,?,?,?,?)', ('evt_' + suffix, 'thr_fixture', kind, sequence, '117471a8-1970-4376-8672-9de66c418579', 'fixture-turn-4'))
                other.commit()
                other.close()
                raise subprocess.TimeoutExpired('fixture tell after adapter acceptance', 25)
            return result

        later = monitor.time.time() + 2000
        with patch.object(monitor, 'bb', side_effect=accepted_then_timeout), patch.object(monitor.time, 'time', return_value=later):
            row = poll(mutate=True)
        goal('Delivery intent is durable before a possibly accepted side effect', prepared_before_call == [True])
        goal('A lost receipt counts its attempt and leaves the sibling observable',
             row['state'] == 'DELIVERY_RECONCILIATION_PENDING' and row['nudges'] == 2 and
             (state / 'monitor-state.json').exists() and polls[-1]['sibling'] == 'COMPLETE')
        (state / 'monitor-state.json').unlink()
        with patch.object(monitor, 'bb', side_effect=accepted_then_timeout), patch.object(monitor.time, 'time', return_value=later + 4000):
            row = poll(mutate=True)
        goal('Losing the poll state cannot erase an uncertain delivery or its budget',
             row['state'] == 'DELIVERY_RECONCILIATION_PENDING' and row['nudges'] == 2 and len(accepted) == 1)
        with patch.object(monitor, 'bb', side_effect=accepted_then_timeout), patch.object(monitor.time, 'time', return_value=later + 8000):
            row = poll(mutate=True)
        goal('Spacing expiry cannot retry an ambiguous accepted delivery',
             row['state'] == 'DELIVERY_RECONCILIATION_PENDING' and len(accepted) == 1)
        shutil.rmtree(state / 'deliveries')
        restore_snapshot(base)
        upgrade_goal['evidence'] = []
        ledger.write_text(json.dumps({'purposes': [original, closed_followup, late, upgrade_goal]}))
        poll()
        (state / 'monitor-state.json').unlink()
        row = poll()
        goal('An unreceipted completed followup stays required after losing the poll state',
             row['state'] != 'COMPLETE' and 'P4' in row['trackedPurposeIds'] and not (state / 'finished.json').exists())
        upgrade_goal['evidence'] = ['source owner accepted recovered followup']
        ledger.write_text(json.dumps({'purposes': [original, closed_followup, late, upgrade_goal]}))
        row = poll()
        goal('Recovered scope can close only after its retained followup receives evidence',
             row['state'] == 'COMPLETE' and 'P4' in row['trackedPurposeIds'])
        other = sqlite3.connect(database)
        other.execute('INSERT INTO events(id,thread_id,type,sequence,provider_thread_id,turn_id) VALUES(?,?,?,?,?,?)', ('evt_requested5', 'thr_fixture', 'client/turn/requested', 13, '117471a8-1970-4376-8672-9de66c418579', 'fixture-turn-5'))
        other.commit()
        other.close()
        row = poll()
        goal('A closed scope cannot finish while a newer adapter request is still pending',
             row['state'] == 'SOURCE_REQUEST_PENDING' and not (state / 'finished.json').exists())
        (state / 'scope-baselines/thr_fixture.json').unlink()
        (state / 'monitor-state.json').unlink()
        row = poll()
        goal('Losing both scope snapshots fails closed while a sibling stays observable',
             row['state'] == 'UNKNOWN' and polls[-1]['sibling'] == 'COMPLETE' and not (state / 'finished.json').exists())
    db = sqlite3.connect(database)
    db.execute('UPDATE threads SET status=? WHERE id=?', ('active', 'thr_sibling'))
    db.execute('UPDATE threads SET environment_id=? WHERE id=?', ('env_thr_fixture', 'thr_sibling'))
    db.commit()
    admitted = monitor.queue_admission(db, {'id': 'thr_fixture', 'status': 'idle'}, {'id': 'env_thr_fixture'})
    goal('A different active write owner blocks admission', not admitted['admitted'])
    db.close()
    # A real BB child-completion notification can arrive after turn/started.
    # It is not a new task or user authority; unknown input still holds.
    notices = sqlite3.connect(home / 'notices.db')
    notices.execute('CREATE TABLE threads(id TEXT,parent_thread_id TEXT,status TEXT,provider_id TEXT,environment_id TEXT,archived_at INTEGER,deleted_at INTEGER)')
    notices.execute('CREATE TABLE events(id TEXT,thread_id TEXT,type TEXT,sequence INTEGER,provider_thread_id TEXT,data TEXT,turn_id TEXT)')
    notices.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?)', ('thr_notices', None, 'idle', 'codex', 'env_notices', None, None))
    notices.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?)', ('thr_notice_child', 'thr_notices', 'idle', 'codex', 'env_child', None, None))
    session = '117471a8-1970-4376-8672-9de66c418579'
    for ident, kind, sequence in [('notice_requested', 'client/turn/requested', 1), ('notice_started', 'turn/started', 2), ('notice_completed', 'turn/completed', 4)]:
        notices.execute('INSERT INTO events(id,thread_id,type,sequence,provider_thread_id,data) VALUES(?,?,?,?,?,?)', (ident, 'thr_notices', kind, sequence, session, '{}'))
    notification = {'direction': 'outbound', 'source': 'tell', 'initiator': 'system',
                    'requestId': 'creq_notice_fixture',
                    'systemMessageKind': 'child-completed',
                    'systemMessageSubject': {'kind': 'thread', 'threadId': 'thr_notice_child'},
                    'target': {'kind': 'auto', 'expectedTurnId': 'fixture-active-turn'},
                    'request': {'method': 'turn/start', 'params': {}}}
    notices.execute('INSERT INTO events(id,thread_id,type,sequence,provider_thread_id,data) VALUES(?,?,?,?,?,?)', ('notice_midturn', 'thr_notices', 'client/turn/requested', 3, None, json.dumps(notification)))
    notices.execute('UPDATE events SET sequence=? WHERE id=?', (5, 'notice_completed'))
    acceptance = {'providerThreadId': session, 'clientRequestId': 'creq_notice_fixture'}
    notices.execute('INSERT INTO events(id,thread_id,type,sequence,provider_thread_id,data) VALUES(?,?,?,?,?,?)', ('notice_accepted', 'thr_notices', 'turn/input/accepted', 4, session, json.dumps(acceptance)))
    notices.execute('UPDATE events SET turn_id=?', ('fixture-active-turn',))
    notices.commit()
    notice_thread = {'id': 'thr_notices', 'status': 'idle', 'providerId': 'codex'}
    notice_environment = {'id': 'env_notices'}
    admitted_notice = monitor.queue_admission(notices, notice_thread, notice_environment)
    goal('A completed turn with an adapter-owned child notice admits the original task lease',
         admitted_notice.get('admitted') and admitted_notice.get('binding', {}).get('topicId') == 'notice_requested')
    with patch.object(monitor, 'bb', side_effect=fake_bb):
        notice_item = {'thread': 'thr_notices', 'nudges': 0}
        if admitted_notice.get('admitted'):
            monitor.queued_delivery(notices, notice_item, admitted_notice, existing_brief)
        goal('Child-completion bookkeeping does not prevent the admitted queued clarification',
             notice_item.get('nudgeReceipt', {}).get('delivery') == 'queued')
    for label, update in [('User input', {'initiator': 'user'}),
                          ('Unknown system notice', {'systemMessageKind': 'other'}),
                          ('Foreign child notice', {'systemMessageSubject': {'kind': 'thread', 'threadId': 'thr_foreign'}}),
                          ('New-turn target', {'target': {'kind': 'new-turn'}})]:
        altered = dict(notification, **update)
        notices.execute('UPDATE events SET data=? WHERE id=?', (json.dumps(altered), 'notice_midturn'))
        notices.commit()
        decision = monitor.queue_admission(notices, notice_thread, notice_environment)
        goal(label + ' during a turn cannot be discarded as completed bookkeeping', not decision.get('admitted'))
    notices.execute('UPDATE events SET data=? WHERE id=?', ('{', 'notice_midturn'))
    notices.commit()
    decision = monitor.queue_admission(notices, notice_thread, notice_environment)
    goal('Malformed mid-turn control metadata fails closed', not decision.get('admitted'))
    notices.execute('UPDATE events SET data=?,sequence=? WHERE id=?', (json.dumps(notification), 6, 'notice_midturn'))
    notices.commit()
    decision = monitor.queue_admission(notices, notice_thread, notice_environment)
    goal('Even a recognized child notice after completion remains pending', not decision.get('admitted'))
    notices.execute('UPDATE events SET sequence=? WHERE id=?', (3, 'notice_midturn'))
    notices.commit()
    for label, update in [('Wrong provider acceptance', {'providerThreadId': 'foreign-session'}),
                          ('Wrong request acceptance', {'clientRequestId': 'foreign-request'})]:
        notices.execute('UPDATE events SET data=? WHERE id=?', (json.dumps(dict(acceptance, **update)), 'notice_accepted'))
        notices.commit()
        decision = monitor.queue_admission(notices, notice_thread, notice_environment)
        goal(label + ' cannot prove a child notice was delivered in this completed turn', not decision.get('admitted'))
    notices.execute('UPDATE events SET data=?,sequence=? WHERE id=?', (json.dumps(acceptance), 6, 'notice_accepted'))
    notices.commit()
    decision = monitor.queue_admission(notices, notice_thread, notice_environment)
    goal('A child notice without an acceptance receipt before completion stays held', not decision.get('admitted'))
    notices.execute('UPDATE events SET sequence=? WHERE id=?', (4, 'notice_accepted'))
    notices.commit()
    stale_target = dict(notification, target={'kind': 'auto', 'expectedTurnId': 'STALE-OTHER-TURN'})
    notices.execute('UPDATE events SET data=? WHERE id=?', (json.dumps(stale_target), 'notice_midturn'))
    notices.commit()
    stale_admission = monitor.queue_admission(notices, notice_thread, notice_environment)
    goal('A stale expected turn ID stays pending despite a matching provider/request acceptance receipt',
         not stale_admission.get('admitted'))
    notices.execute('UPDATE events SET data=? WHERE id=?', (json.dumps(notification), 'notice_midturn'))
    notices.commit()
    for field_id, label in [('notice_accepted', 'Acceptance from another turn'), ('notice_completed', 'Completion from another turn'), ('notice_started', 'Missing start turn identity')]:
        notices.execute('UPDATE events SET turn_id=? WHERE id=?', (None if field_id == 'notice_started' else 'foreign-turn', field_id))
        notices.commit()
        decision = monitor.queue_admission(notices, notice_thread, notice_environment)
        goal(label + ' cannot settle the original task', not decision.get('admitted'))
        notices.execute('UPDATE events SET turn_id=? WHERE id=?', ('fixture-active-turn', field_id))
        notices.commit()
    admitted_notice = monitor.queue_admission(notices, notice_thread, notice_environment)
    altered = dict(notification, initiator='user')
    notices.execute('UPDATE events SET data=? WHERE id=?', (json.dumps(altered), 'notice_midturn'))
    notices.commit()
    with patch.object(monitor, 'bb', side_effect=fake_bb):
        before = sum(args[:2] == ['thread', 'tell'] for args in calls)
        notice_item = {'thread': 'thr_notices', 'nudges': 1}
        if admitted_notice.get('admitted'):
            monitor.queued_delivery(notices, notice_item, admitted_notice, existing_brief)
        goal('Changed notification metadata after admission blocks delivery without a tell',
             admitted_notice.get('admitted') and not notice_item.get('nudgeReceipt') and
             sum(args[:2] == ['thread', 'tell'] for args in calls) == before)
    notices.close()
    # Native UI reads and title updates must not discard authoritative source
    # progress or prevent an independent sibling from being observed.
    surface_db_path = home / 'surface.db'
    surface_db = sqlite3.connect(surface_db_path)
    surface_db.execute('CREATE TABLE threads(id TEXT,parent_thread_id TEXT,status TEXT,provider_id TEXT,environment_id TEXT,archived_at INTEGER,deleted_at INTEGER)')
    surface_db.execute('CREATE TABLE events(id TEXT,thread_id TEXT,type TEXT,sequence INTEGER,provider_thread_id TEXT,data TEXT,turn_id TEXT)')
    surface_db.executemany('INSERT INTO threads VALUES(?,?,?,?,?,?,?)', [
        ('thr_surface', None, 'active', 'codex', 'env_surface', None, None),
        ('thr_surface_sibling', None, 'idle', 'codex', 'env_sibling', None, None),
        ('thr_surface_child', 'thr_surface', 'active', 'codex', 'env_child', None, None)])
    surface_db.commit()
    surface_db.close()
    surface_scopes = home / 'surface-scopes'
    surface_scopes.mkdir()
    (surface_scopes / 'thr_surface.json').write_text(json.dumps({'purposes': [{'id': 'P1', 'status': 'open'}]}))
    (surface_scopes / 'thr_surface_sibling.json').write_text(json.dumps({'purposes': [original]}))
    codex_handle = 'term_11111111-2222-4333-8444-555555555556'
    child_handle = 'term_11111111-2222-4333-8444-555555555555'
    faults = [
        ('Codex terminal read timeout', ['terminal', 'show'], codex_handle, 'timeout'),
        ('Coordinator card rename timeout', ['canvas', 'rename'], 'chat_surface', 'timeout'),
        ('Codex card rename timeout', ['canvas', 'rename'], 'codex_surface', 'timeout'),
        ('Worker canvas inventory timeout', ['canvas', 'list'], 'id:ws_surface', 'timeout'),
        ('Worker terminal inventory timeout', ['terminal', 'list'], 'id:ws_surface', 'timeout'),
        ('Worker card rename timeout', ['canvas', 'rename'], 'worker_surface', 'timeout'),
        ('Worker terminal rename timeout', ['terminal', 'rename'], child_handle, 'timeout'),
        ('Unavailable native binary during worker update', ['terminal', 'rename'], child_handle, 'missing')]
    for index, (label, prefix, identifier, failure_kind) in enumerate(faults):
        fixture_root = home / ('surface-case-' + str(index))
        jobs = fixture_root / 'jobs'
        codex = jobs / 'codex-surface-coordinator'
        codex.mkdir(parents=True)
        (codex / 'binding.json').write_text(json.dumps({'project': 'surface', 'terminalHandle': codex_handle,
                                                      'nodeId': 'codex_surface', 'runtimeId': 'surface-runtime'}))
        surface_config = dict(config, stateRoot=str(fixture_root / 'state'), scopeRoot=str(surface_scopes),
                              bbDatabase=str(surface_db_path), jobsRoot=str(jobs), lockFile=str(fixture_root / 'lock'))
        surface_config['targets'] = [
            {'thread': 'thr_surface', 'purposes': ['P1'], 'project': 'surface', 'workspace': 'ws_surface',
             'node': 'chat_surface', 'providerJournalRoot': str(home / 'journals'),
             'workerNodes': [{'thread': 'thr_surface_child', 'node': 'worker_surface', 'name': 'Worker'}]},
            {'thread': 'thr_surface_sibling', 'purposes': ['P1'], 'project': 'surface_sibling',
             'workspace': 'ws_sibling', 'node': 'chat_sibling', 'providerJournalRoot': str(home / 'journals')}]
        surface_path = fixture_root / 'config.json'
        surface_path.write_text(json.dumps(surface_config))
        monitor.configure(surface_path)
        attempted = []
        fault_triggered = []

        def surface_process(argv, **kwargs):
            assert argv[0] == 'elyra', 'This slice authorizes only the non-billable native fixture'
            attempted.append(argv[1:3])
            if argv[1:3] == prefix and identifier in argv:
                fault_triggered.append(True)
                if failure_kind == 'missing':
                    raise FileNotFoundError(2, 'Fixture native surface is unavailable')
                raise subprocess.TimeoutExpired(argv, kwargs.get('timeout', 15), output=b'fixture partial output', stderr=b'fixture error detail')
            workspace = 'ws_surface' if 'id:ws_surface' in argv else 'ws_sibling'
            if argv[1:3] == ['chat', 'list']:
                payload = {'ok': True, 'result': {'chats': [{'nodeId': 'chat_surface' if workspace == 'ws_surface' else 'chat_sibling',
                                                          'title': 'old title', 'working': False}]}}
            elif argv[1:3] == ['terminal', 'show']:
                payload = {'ok': True, '_meta': {'runtimeId': 'surface-runtime'}, 'result': {'terminal': {
                    'handle': codex_handle, 'worktreeId': 'ws_surface', 'connected': True}}}
            elif argv[1:3] == ['canvas', 'list']:
                payload = {'ok': True, 'result': {'nodes': [{'id': 'worker_surface', 'type': 'terminal',
                    'title': 'old title', 'sessionId': 'surface-child-session'}]}}
            elif argv[1:3] == ['terminal', 'list']:
                payload = {'ok': True, 'result': {'terminals': [{'handle': child_handle, 'worktreeId': 'ws_surface',
                    'tabId': 'surface-child-session', 'connected': True, 'title': 'old title'}]}}
            else:
                assert argv[1:3] in (['canvas', 'rename'], ['terminal', 'rename'])
                payload = {'ok': True}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload))

        with patch.object(monitor, 'bb', side_effect=fake_bb), patch.object(monitor.subprocess, 'run', side_effect=surface_process), patch.object(monitor, 'native_review_state', return_value={'state': 'IDLE', 'pending': []}):
            try:
                observed = monitor.run(mutate=True)
                exception = None
            except (OSError, subprocess.TimeoutExpired) as failure:
                observed, exception = None, type(failure).__name__
        states = {key: row['state'] for key, row in observed['targets'].items()} if observed else {}
        diagnostics = observed['targets']['thr_surface'].get('nativeSurfaceFailures', []) if observed else []
        diagnostic_ok = len(diagnostics) == 1 and diagnostics[0]['operation'] == prefix
        if diagnostic_ok and failure_kind == 'timeout':
            diagnostic_ok = (diagnostics[0]['cause'] == 'timeout' and diagnostics[0]['errorType'] == 'TimeoutExpired'
                             and diagnostics[0]['returnCode'] == 124 and diagnostics[0]['timeoutSeconds'] == 15
                             and diagnostics[0]['stdout'] == {'bytes': 22, 'sha256': hashlib.sha256(b'fixture partial output').hexdigest()}
                             and diagnostics[0]['stderr'] == {'bytes': 20, 'sha256': hashlib.sha256(b'fixture error detail').hexdigest()})
        elif diagnostic_ok:
            diagnostic_ok = diagnostics[0]['cause'] == 'os_error' and diagnostics[0]['errorType'] == 'FileNotFoundError' and diagnostics[0]['returnCode'] == 127 and diagnostics[0]['errno'] == 2
        durable_path = fixture_root / 'state/monitor-state.json'
        durable_diagnostics = json.loads(durable_path.read_text())['targets']['thr_surface'].get('nativeSurfaceFailures', []) if durable_path.exists() else []
        goal(label + ' preserves source progress and the sibling in a durable poll receipt',
             states == {'thr_surface': 'RUNNING', 'thr_surface_sibling': 'COMPLETE'}
             and durable_diagnostics == diagnostics and prefix in attempted and bool(fault_triggered) and diagnostic_ok)
        goals[-1]['observed'] = {'states': states, 'exception': exception, 'fault': label, 'faultTriggered': bool(fault_triggered), 'diagnostics': diagnostics}
    monitor.configure(config_path)
    spec = importlib.util.spec_from_file_location('controller_workflow', HERE / 'controller.py')
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    control = {'loaded': False, 'bootstraps': 0}

    def launchctl_fixture(argv, **kwargs):
        assert argv[0] == 'launchctl'
        if argv[1] == 'print':
            return subprocess.CompletedProcess(argv, 0 if control['loaded'] else 1, stdout='')
        assert argv[1] == 'bootstrap'
        control['loaded'] = True
        control['bootstraps'] += 1
        return subprocess.CompletedProcess(argv, 0, stdout='')

    def rejects(call):
        try:
            call()
        except ValueError:
            return True
        return False

    with patch.object(controller.Path, 'home', return_value=home / 'operator-home'), patch.object(controller.sys, 'platform', 'darwin'), patch.object(controller.subprocess, 'run', side_effect=launchctl_fixture), redirect_stdout(io.StringIO()):
        installed = controller.stage(config_path, home / 'installed')
        plist = Path(installed['plist'])
        expected = plist.read_bytes()
        wrong = plistlib.loads(expected)
        wrong['ProgramArguments'][1] = '/unowned/controller.py'
        plist.write_bytes(plistlib.dumps(wrong))
        refused = rejects(lambda: controller.activate(config_path))
        goal('A plist that points at another controller cannot activate despite a matching config path', refused and control['bootstraps'] == 0)
        plist.write_bytes(expected)
        with (home / 'shared.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            refused = rejects(lambda: controller.stage(config_path, home / 'installed'))
        goal('A held poll lock blocks interleaved scheduler staging', refused and control['bootstraps'] == 0)
        controller.activate(config_path)
        first = json.loads((state / 'installation.json').read_text())
        repeated = controller.stage(config_path, home / 'installed')
        goal('Restaging the loaded immutable version preserves its activation receipt',
             first['activated'] and repeated['activated'] and repeated['activatedAt'] == first['activatedAt'] and control['bootstraps'] == 1)
        control['loaded'] = False
        installed_readme = Path(installed['installPath']) / 'README.md'
        installed_readme.write_text(installed_readme.read_text() + '\nchanged after stage\n')
        refused = rejects(lambda: controller.activate(config_path))
        goal('An installed README changed after staging blocks activation', refused and control['bootstraps'] == 1)
        frames = home / 'digest-boundaries'
        frames.mkdir()
        for name, raw in [('monitor.py', b'a'), ('controller.py', b'b'), ('README.md', b'c')]:
            (frames / name).write_bytes(raw)
        with patch.object(controller, 'HERE', frames):
            digest1 = controller.artifact_digest()
            (frames / 'monitor.py').write_bytes(b'ab')
            (frames / 'controller.py').write_bytes(b'')
            digest2 = controller.artifact_digest()
        goal('Different file boundaries cannot reuse the same installed artifact identity', digest1 != digest2)
        fresh_config = dict(config)
        fresh_state = home / 'fresh-state'
        fresh_scopes = home / 'fresh-scopes'
        fresh_scopes.mkdir()
        fresh_database = home / 'fresh.db'
        fresh_db = sqlite3.connect(fresh_database)
        fresh_db.execute('CREATE TABLE threads(id TEXT,parent_thread_id TEXT,status TEXT,provider_id TEXT,environment_id TEXT,archived_at INTEGER,deleted_at INTEGER)')
        fresh_db.execute('CREATE TABLE events(id TEXT,thread_id TEXT,type TEXT,sequence INTEGER,provider_thread_id TEXT)')
        fresh_db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?)', ('thr_newfixture', None, 'idle', 'codex', 'env_newfixture', None, None))
        fresh_db.commit()
        fresh_db.close()
        (fresh_scopes / 'thr_newfixture.json').write_text(json.dumps({'purposes': [original]}))
        fresh_config.update({'stateRoot': str(fresh_state), 'scopeRoot': str(fresh_scopes), 'bbDatabase': str(fresh_database),
                             'lockFile': str(home / 'fresh.lock'), 'targets': [dict(config['targets'][0], thread='thr_newfixture')],
                             'scheduler': {'label': 'local.agent-config-kit.fleet.freshfixture', 'intervalSeconds': 300}})
        fresh_path = home / 'fresh-config.json'
        fresh_path.write_text(json.dumps(fresh_config))
        staged = controller.stage(fresh_path, home / 'fresh-installed')
        staged_controller_path = Path(staged['installPath']) / 'controller.py'
        spec = importlib.util.spec_from_file_location('staged_controller_consumer', staged_controller_path)
        staged_controller = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(staged_controller)
        fresh_monitor, _, _ = staged_controller.bindings(fresh_path)
        with patch.object(fresh_monitor, 'bb', return_value=[]), patch.object(fresh_monitor, 'surface', return_value=subprocess.CompletedProcess([], 0, stdout='{"ok":true,"result":{"chats":[]}}')), patch.object(fresh_monitor, 'native_review_state', return_value={'state': 'IDLE', 'pending': []}):
            fresh_states = [fresh_monitor.run(mutate=False)['targets']['thr_newfixture']['state'] for _ in range(3)]
        goal('Stage before the first poll creates a usable fresh baseline instead of locking into unknown',
             Path(fresh_monitor.__file__).parent.resolve() == Path(staged['installPath']).resolve() and fresh_states == ['COMPLETE'] * 3 and (fresh_state / 'scope-baselines/thr_newfixture.json').exists())
        goals[-1]['observed'] = {'states': fresh_states, 'monitorPath': str(fresh_monitor.__file__), 'stagedPath': staged['installPath'],
                                 'baselineExists': (fresh_state / 'scope-baselines/thr_newfixture.json').exists()}

packet = {'persona': 'Fleet operator', 'target': {'stack': 'Portable monitor and real metadata guard with disposable BB/provider fixtures',
          'monitorSha256': hashlib.sha256((HERE / 'monitor.py').read_bytes()).hexdigest()}, 'polls': polls,
          'goals': goals, 'verdict': 'PASS' if all(g['verdict'] == 'PASS' for g in goals) else 'FAIL'}
if args.output:
    args.output.write_text(json.dumps(packet, indent=2) + '\n')
print(json.dumps(packet, indent=2))
raise SystemExit(0 if packet['verdict'] == 'PASS' else 1)
