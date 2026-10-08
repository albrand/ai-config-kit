"""Configurable, single-flight continuation across BB and Elyra.

Source scopes are task state, never authority in another session.
Active targets are never steered; every source input uses its queue.
"""
import argparse
import fcntl
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# Deployment bindings live in private operator configuration, never this kit.
ROOT = None
BB = ['bb']
ELYRA = ['elyra']
TARGETS = []
DATABASE = Path.home() / '.bb/bb.db'
SCOPE_ROOT = Path.home() / '.local/state/agent-quality/scope'
HOOK_STATUS = Path.home() / 'Library/Application Support/elyra/agent-hooks/last-status.json'
JOBS_ROOT = None
LOCK_FILE = None
INPUT_GUARD = Path.home() / '.codex/skills/native-agent-surface/scripts/session-input-guard.py'


def configure(path):
    global ROOT, BB, ELYRA, TARGETS, DATABASE, SCOPE_ROOT, HOOK_STATUS, JOBS_ROOT, LOCK_FILE, INPUT_GUARD
    config = json.loads(Path(path).read_text())
    if config.get('schemaVersion') != 1:
        raise ValueError('Unsupported fleet bridge configuration')
    def absolute(name, default=None):
        value = config.get(name, default)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError('Configuration requires absolute path: ' + name)
        return Path(value)
    def command(name, default):
        value = config.get(name, default)
        if not isinstance(value, list) or not value or any(not isinstance(a, str) or not a or chr(0) in a for a in value):
            raise ValueError('Invalid command argv: ' + name)
        return value
    ROOT = absolute('stateRoot')
    BB = command('bbCommand', ['bb'])
    ELYRA = command('elyraCommand', ['elyra'])
    DATABASE = absolute('bbDatabase', str(DATABASE))
    SCOPE_ROOT = absolute('scopeRoot', str(SCOPE_ROOT))
    HOOK_STATUS = absolute('hookStatus', str(HOOK_STATUS))
    JOBS_ROOT = absolute('jobsRoot', str(ROOT / 'jobs'))
    LOCK_FILE = absolute('lockFile', str(ROOT / 'monitor.lock'))
    INPUT_GUARD = absolute('inputGuard', str(INPUT_GUARD))
    TARGETS = config.get('targets')
    if not isinstance(TARGETS, list) or not TARGETS:
        raise ValueError('At least one explicit target is required')
    ids = set()
    for target in TARGETS:
        if not isinstance(target, dict) or not isinstance(target.get('thread'), str) or not target['thread'].startswith('thr_') or not all(c.isalnum() or c == '_' for c in target['thread']):
            raise ValueError('Invalid source thread identity')
        if target['thread'] in ids:
            raise ValueError('Duplicate source thread identity')
        ids.add(target['thread'])
        if not isinstance(target.get('purposes'), list) or not target['purposes'] or any(not isinstance(p, str) or not p for p in target['purposes']):
            raise ValueError('Explicit original purpose floor is required')
        for field in ['workspace', 'node', 'project', 'providerJournalRoot']:
            if not isinstance(target.get(field), str) or not target[field]:
                raise ValueError('Missing target binding: ' + field)
        if not Path(target['providerJournalRoot']).is_absolute():
            raise ValueError('Provider journal root must be absolute')
    return config


def classify(status, purposes, queued, owners, job_running):
    if not purposes:
        return 'UNKNOWN'
    if any(x not in {'done', 'open', 'blocked-on-user'} for x in [p.get('status') for p in purposes]):
        return 'UNKNOWN'
    if status in {'active', 'starting', 'stopping'} or job_running:
        return 'RUNNING'
    if queued:
        return 'QUEUED'
    if owners:
        return 'OWNER_HOLD'
    if all(p.get('status') == 'done' and p.get('evidence') for p in purposes):
        return 'COMPLETE' if status == 'idle' else 'ERROR_HOLD'
    if any(p.get('status') == 'open' for p in purposes) and status == 'idle':
        return 'RUNNABLE_IDLE'
    if all(p.get('status') in {'done', 'blocked-on-user'} for p in purposes):
        return 'BLOCKED'
    return 'ERROR_HOLD'

def source_purposes(ledger, required, tracked=(), known=None):
    # Keep the original purposes and every followup observed unfinished. Older
    # closed history stays outside this continuation. Scope is not authority.
    purposes = ledger.get('purposes') if isinstance(ledger, dict) else None
    if not isinstance(purposes, list) or any(not isinstance(p, dict) or not isinstance(p.get('id'), str) or not p['id'] for p in purposes):
        return [], False
    ids = [p['id'] for p in purposes]
    required_ids = set(required) | set(tracked)
    if known is not None:
        # New goals remain required even when opened and closed between polls.
        # The first snapshot distinguishes older completed history from additions.
        required_ids |= set(ids) - set(known)
    if len(set(ids)) != len(ids) or not required_ids.issubset(ids):
        return [], False
    return [p for p in purposes if p['id'] in required_ids or p.get('status') != 'done'], True

def revision_state(ledger, required):
    revisions = ledger.get('accepted_revisions', [])
    if not isinstance(revisions, list) or any(not isinstance(r, dict) or not isinstance(r.get('quote'), str) or not r['quote'].strip() for r in revisions):
        return [], 'Accepted revision metadata invalid'
    def stamp(value):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.timestamp() if parsed.tzinfo else None
        except (AttributeError, TypeError, ValueError):
            return None
    rows = ledger.get('purposes', [])
    if not isinstance(rows, list):
        return [], 'Source purpose metadata invalid'
    original = [p for p in rows if isinstance(p, dict) and p.get('id') in required]
    original_closure = None
    if len(original) == len(required) and all(p.get('status') == 'done' and p.get('evidence') and stamp(p.get('status_marked_at')) is not None for p in original):
        original_closure = min(stamp(p['status_marked_at']) for p in original)
    pending = []
    for revision in revisions:
        accepted = stamp(revision.get('accepted_at'))
        explicit = revision.get('status') == 'done' and bool(revision.get('evidence'))
        if explicit or (accepted is not None and original_closure is not None and accepted <= original_closure):
            continue
        pending.append(revision)
    return pending, None

def read_scope_ledger(path):
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {}, 'Source scope ledger shape invalid'
        return data, None
    except FileNotFoundError:
        return {}, 'Source scope ledger missing'
    except (ValueError, OSError):
        return {}, 'Source scope ledger unavailable or invalid'

def previous_scope(last, required):
    if not last:
        return [], None, None
    def valid(value):
        return isinstance(value, list) and all(isinstance(x, str) and x for x in value) and len(set(value)) == len(value) and set(required).issubset(value)
    tracked = last.get('trackedPurposeIds', list(required))
    error = None
    if not valid(tracked):
        tracked = list(required)
        error = 'Prior tracked scope invalid; completion cannot be inferred'
    known = last.get('knownPurposeIds', tracked)
    if not valid(known) or not set(tracked).issubset(known):
        known = tracked
    return tracked, known, error

def can_nudge(thread, route):
    return bool(thread.get('status') == 'idle' and not thread.get('queuedMessageCount') and thread.get('providerId') in {'codex', 'claude-code'} and route.get('routable') and route.get('providerId') == thread.get('providerId'))

def active_descendants(db, thread):
    # The coordinator may legitimately be idle while its source workers own
    # unfinished work. Read the real parent graph, including deeper lanes.
    return [{'thread': row[0], 'parentThread': row[1], 'status': row[2], 'providerId': row[3]}
            for row in db.execute('''WITH RECURSIVE descendants(id) AS (
                SELECT id FROM threads WHERE parent_thread_id=?
                UNION SELECT t.id FROM threads t JOIN descendants d ON t.parent_thread_id=d.id
            ) SELECT t.id,t.parent_thread_id,t.status,t.provider_id FROM threads t
              JOIN descendants d ON t.id=d.id
              WHERE t.id<>? AND t.archived_at IS NULL AND t.deleted_at IS NULL
              AND t.status IN ('active','starting','stopping')''', (thread, thread))]

def descendant_work(db, thread, scope_root=None, queue_lookup=None):
    scope_root = scope_root or SCOPE_ROOT
    queue_lookup = queue_lookup or (lambda ident: bb(['thread', 'queue', 'list', ident, '--json']))
    rows = db.execute('''WITH RECURSIVE descendants(id) AS (
        SELECT id FROM threads WHERE parent_thread_id=?
        UNION SELECT t.id FROM threads t JOIN descendants d ON t.parent_thread_id=d.id
    ) SELECT t.id,t.parent_thread_id,t.status,t.provider_id FROM threads t
      JOIN descendants d ON t.id=d.id WHERE t.id<>? AND t.archived_at IS NULL
      AND t.deleted_at IS NULL''', (thread, thread))
    work = []
    for ident, parent, status, provider in rows:
        entry = {'thread': ident, 'parentThread': parent, 'status': status, 'providerId': provider}
        if status in {'active', 'starting', 'stopping'}:
            entry['hold'] = 'RUNNING'
        elif status == 'error':
            entry['hold'] = 'ERROR'
        else:
            if not isinstance(ident, str) or not ident.startswith('thr_') or not all(c.isalnum() or c == '_' for c in ident):
                entry['hold'] = 'IDENTITY_UNKNOWN'
            else:
                try:
                    queue = queue_lookup(ident)
                except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
                    entry['hold'] = 'QUEUE_UNKNOWN'
                    work.append(entry)
                    continue
                if not isinstance(queue, list):
                    entry['hold'] = 'QUEUE_UNKNOWN'
                    work.append(entry)
                    continue
                if queue:
                    entry['hold'] = 'QUEUED'
                    work.append(entry)
                    continue
                ledger = scope_root / (ident + '.json')
                if ledger.exists():
                    try:
                        purposes = json.loads(ledger.read_text())['purposes']
                        if not isinstance(purposes, list) or any(not isinstance(p, dict) or p.get('status') not in {'done', 'open', 'blocked-on-user'} for p in purposes):
                            entry['hold'] = 'SCOPE_UNKNOWN'
                        else:
                            outstanding = [p for p in purposes if p['status'] != 'done' or not p.get('evidence')]
                            if outstanding:
                                entry['hold'] = 'UNFINISHED_SCOPE'
                                entry['purposeIds'] = [p.get('id') for p in outstanding]
                    except (OSError, ValueError, KeyError, TypeError):
                        entry['hold'] = 'SCOPE_UNKNOWN'
                else:
                    entry['hold'] = 'SCOPE_UNKNOWN'
                    entry['detail'] = 'Idle source owner has no readable scope ledger on this host'
        if entry.get('hold'):
            work.append(entry)
    return work

def completion_guard(classification, review_state, child_holds):
    if child_holds and classification in {'COMPLETE', 'RUNNABLE_IDLE', 'BLOCKED'}:
        return 'CHILD_WORK_PENDING'
    if classification == 'COMPLETE' and review_state.get('state') != 'IDLE':
        return 'NATIVE_REVIEW_PENDING' if review_state.get('state') in {'RUNNING', 'TOOL_WAIT', 'REVIEW_WAIT'} else 'NATIVE_STATUS_UNKNOWN'
    return classification

def reconciliation_needed(status, purposes, queued, owners, child_holds, pending_revisions=()):
    # Unknown idle child receipts block completion, but must not strand their
    # existing coordinator. Only that owner may reconcile or resume them.
    return bool(status == 'idle' and not queued and not owners and child_holds
                and (any(p.get('status') == 'open' for p in purposes) or pending_revisions)
                and all(x.get('status') not in {'active', 'starting', 'stopping'}
                        and x.get('hold') != 'QUEUED' for x in child_holds))

def worker_terminal(node, terminals, workspace):
    # This binding permits title metadata only, never provider/session input.
    session = node.get('sessionId')
    if not isinstance(session, str) or not session:
        return None
    matches = [t for t in terminals if t.get('tabId') == session and t.get('worktreeId') == workspace]
    if not matches:
        return None
    for terminal in matches:
        handle = terminal.get('handle')
        if not isinstance(handle, str) or not handle.startswith('term_') or not terminal.get('connected'):
            return None
        try:
            if str(uuid.UUID(handle[5:])) != handle[5:]:
                return None
        except (ValueError, AttributeError):
            return None
    if len(matches) > 1:
        leaves = {t.get('leafId') for t in matches}
        if len(leaves) != 1 or not isinstance(next(iter(leaves)), str) or not next(iter(leaves)):
            return None
    return min(matches, key=lambda t: t['handle'])

def runtime_inventory(reply, resource='terminals', name='Terminal'):
    if reply.returncode:
        return [], name + ' inventory command failed'
    try:
        data = json.loads(reply.stdout)
        terms = data.get('result', {}).get(resource)
        if not data.get('ok') or not isinstance(terms, list) or any(not isinstance(t, dict) for t in terms):
            return [], name + ' inventory shape invalid'
        return terms, None
    except (ValueError, TypeError, AttributeError):
        return [], name + ' inventory JSON invalid'

def terminal_inventory(reply):
    return runtime_inventory(reply)

def terminal_snapshot(reply):
    if reply.returncode:
        return {}, 'Native Codex terminal command failed'
    try:
        data = json.loads(reply.stdout)
        term = data.get('result', {}).get('terminal')
        if not data.get('ok') or not isinstance(term, dict):
            return {}, 'Native Codex terminal shape invalid'
        return {'terminal': term, 'runtimeId': data.get('_meta', {}).get('runtimeId')}, None
    except (ValueError, TypeError, AttributeError):
        return {}, 'Native Codex terminal JSON invalid'

def pending_tool_state(rows, now, working=True):
    requests, results = {}, set()
    malformed = False
    last_request, last_final = -1, -1
    for row in rows:
        if not isinstance(row, dict):
            malformed = True
            continue
        if row.get('type') not in {'user', 'assistant'}:
            continue
        message = row.get('message')
        if not isinstance(message, dict):
            malformed = True
            continue
        content = message.get('content')
        if isinstance(content, str):
            content = []
        elif not isinstance(content, list):
            malformed = True
            continue
        if row.get('type') == 'user' and not any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in content):
            last_request = row.get('uuid') or id(row)
            last_final = -1
        if row.get('type') == 'assistant' and message.get('stop_reason') == 'end_turn':
            last_final = row.get('uuid') or id(row)
        # New prompt text never proves cancellation of an unresolved request.
        for block in content:
            if not isinstance(block, dict):
                malformed = True
                continue
            if block.get('type') == 'tool_use' and block.get('id'):
                stamp = row.get('timestamp')
                try:
                    at = datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()
                except (AttributeError, ValueError, TypeError):
                    at = None
                    malformed = True
                requests[block['id']] = {'id': block['id'], 'name': block.get('name'), 'at': at}
            elif block.get('type') == 'tool_result':
                results.add(block.get('tool_use_id'))
    pending = [x for ident, x in requests.items() if ident not in results]
    if malformed:
        return {'state': 'UNKNOWN', 'pending': pending, 'detail': 'Malformed provider metadata; unresolved requests retained'}
    if pending:
        state = 'TOOL_WAIT' if not working or any(now - x['at'] >= 60 for x in pending) else 'RUNNING'
    elif working:
        state = 'RUNNING'
    elif last_request != -1 and last_final == -1:
        state = 'REVIEW_WAIT'
    else:
        state = 'IDLE'
    return {'state': state, 'pending': pending}

def native_review_state(chat, target, entries=None, journal_rows=None, now=None):
    if chat is None:
        return {'state': 'UNKNOWN'}
    if chat.get('worktreeId') != target['workspace'] or chat.get('nodeId') != target['node']:
        return {'state': 'UNKNOWN', 'detail': 'Native workspace/card binding mismatch'}
    statuses = HOOK_STATUS
    try:
        entries = list(json.loads(statuses.read_text()).get('entries', {}).values()) if entries is None else entries
        matches = [x for x in entries if x.get('tabId') == chat.get('tabId') and x.get('payload', {}).get('agentType') == 'claude']
        if len(matches) != 1:
            return {'state': 'UNKNOWN', 'detail': 'Provider metadata is not uniquely bound'}
        session = matches[0].get('providerSession', {}).get('id')
        if not isinstance(session, str) or str(uuid.UUID(session)) != session:
            return {'state': 'UNKNOWN', 'detail': 'Provider session identity unavailable'}
        journal = Path(target.get('providerJournalRoot', '/unconfigured-provider-journals')) / (session + '.jsonl')
        rows = [json.loads(line) for line in journal.read_text().splitlines()] if journal_rows is None else journal_rows
        state = pending_tool_state(rows, time.time() if now is None else now, bool(chat.get('working')))
        state['providerSession'] = session
        return state
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return {'state': 'UNKNOWN', 'detail': 'Provider metadata unavailable; no inferred completion'}

def bb(args):
    result = subprocess.run(BB + args, capture_output=True, text=True, timeout=25)
    if result.returncode:
        raise RuntimeError('BB metadata/action refused: command=' + args[0] + ', exit=' + str(result.returncode))
    return json.loads(result.stdout)

def source_snapshot(db, ident):
    # Enriched `thread show` fetches PR/spend data. Lifecycle polling needs only
    # canonical adapter metadata, already used for owners and descendants.
    row = db.execute('SELECT id,status,provider_id,environment_id,archived_at,deleted_at FROM threads WHERE id=?', (ident,)).fetchone()
    if row is None or row[4] is not None or row[5] is not None or not row[3]:
        raise RuntimeError('Live source thread/environment binding unavailable')
    return {'thread': {'id': row[0], 'status': row[1], 'providerId': row[2], 'environmentId': row[3]},
            'environment': {'id': row[3]}}

def surface(args):
    try:
        return subprocess.run(ELYRA + args, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(ELYRA + args, 124, stdout='', stderr='Surface unavailable')

def save(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)

def queue_admission(db, thread, environment):
    """Admit from actual BB adapter events; scope and prompt text are excluded."""
    ident = thread['id']
    session = db.execute('SELECT provider_thread_id FROM events WHERE thread_id=? AND provider_thread_id IS NOT NULL ORDER BY sequence DESC LIMIT 1', (ident,)).fetchone()
    started = db.execute("SELECT id,sequence FROM events WHERE thread_id=? AND type='turn/started' ORDER BY sequence DESC LIMIT 1", (ident,)).fetchone()
    requested = db.execute("SELECT id,sequence FROM events WHERE thread_id=? AND type='client/turn/requested' ORDER BY sequence DESC LIMIT 1", (ident,)).fetchone()
    ended = db.execute("SELECT sequence FROM events WHERE thread_id=? AND type='turn/completed' ORDER BY sequence DESC LIMIT 1", (ident,)).fetchone()
    owners = [r[0] for r in db.execute("SELECT id FROM threads WHERE environment_id=? AND status IN ('active','starting','stopping') AND archived_at IS NULL AND deleted_at IS NULL", (environment['id'],))]
    if thread.get('status') != 'idle' or owners or not session or not started or not requested or not ended or ended[0] <= started[1]:
        return {'admitted': False, 'reason': 'Completed adapter turn and exclusive idle workspace required'}
    lease = {'schema_version': 1, 'workspace_id': environment['id'], 'session_id': session[0],
             'lease_id': started[0], 'topic_id': requested[0], 'epoch': started[1],
             'status': 'completed', 'write_owner': ident}
    envelope = {'schema_version': 1, 'workspace_id': environment['id'], 'session_id': session[0],
                'lease_id': None, 'topic_id': None, 'input_class': 'handoff',
                'attribution': {'kind': 'dispatch', 'authenticated': False, 'authority': None},
                'resume_packet_ref': None, 'resume_packet_validated': False,
                'topic_relation_verified': False, 'source_workspace_id': None, 'write_owner': ident}
    folder = ROOT / 'admissions'
    folder.mkdir(exist_ok=True, mode=0o700)
    packet = folder / (ident + '.json')
    save(packet, {'current_lease': lease, 'envelope': envelope})
    guard = subprocess.run([sys.executable, str(INPUT_GUARD), '--input', str(packet)], capture_output=True, text=True, timeout=15)
    try:
        decision = json.loads(guard.stdout)
    except ValueError:
        return {'admitted': False, 'reason': 'Metadata admission returned invalid output', 'exitCode': guard.returncode}
    save(folder / (ident + '-result.json'), decision)
    return {'admitted': guard.returncode == 0 and decision.get('decision') == 'route_fresh',
            'decision': decision.get('decision'), 'exitCode': guard.returncode}

def run(mutate=False):
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with LOCK_FILE.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'SINGLE_FLIGHT_HELD'}
        prior_path = ROOT / 'monitor-state.json'
        prior = json.loads(prior_path.read_text()) if prior_path.exists() else {'targets': {}, 'allComplete': False}
        db = sqlite3.connect(DATABASE.as_uri() + '?mode=ro', uri=True)
        results = []
        for target in TARGETS:
            native = surface(['chat', 'list', '--workspace', 'id:' + target['workspace'], '--json'])
            chats, chat_error = runtime_inventory(native, 'chats', 'Native chat')
            thread = target['thread']
            s = source_snapshot(db, thread)
            t, env = s['thread'], s['environment']
            ledger_path = SCOPE_ROOT / (thread + '.json')
            ledger, ledger_error = read_scope_ledger(ledger_path)
            last = prior.get('targets', {}).get(thread, {})
            # An upgrade cannot bless unknown IDs as old completed history.
            tracked, known, baseline_error = previous_scope(last, target['purposes'])
            purposes, purposes_valid = source_purposes(ledger, target['purposes'], tracked, known)
            pending_revisions, revision_error = revision_state(ledger, target['purposes'])
            observed_purpose_ids = [p['id'] for p in purposes] or target['purposes']
            queue = bb(['thread', 'queue', 'list', thread, '--json'])
            owners = [row[0] for row in db.execute("select id from threads where environment_id=? and status in ('active','starting','stopping') and archived_at is null and deleted_at is null", (env['id'],)) if row[0] != thread]
            source_workers = active_descendants(db, thread)
            all_child_work = descendant_work(db, thread)
            child_holds = [x for x in all_child_work if x['hold'] != 'RUNNING']
            native_jobs = []
            for folder in JOBS_ROOT.iterdir() if JOBS_ROOT.is_dir() else []:
                if not folder.is_dir() or not (folder / 'binding.json').exists():
                    continue
                job = json.loads((folder / 'binding.json').read_text())
                if job['project'] != target['project']:
                    continue
                completion = json.loads((folder / 'completion.json').read_text()) if (folder / 'completion.json').exists() else None
                launch = json.loads((folder / 'launch.json').read_text()) if (folder / 'launch.json').exists() else None
                alive = False
                if launch and not completion:
                    try:
                        command = subprocess.run(['ps', '-p', str(launch['wrapperPid']), '-o', 'comm='], capture_output=True, text=True).stdout.strip()
                        alive = Path(command).name.lower().startswith('python')
                    except OSError:
                        alive = False
                native_jobs.append({'job': folder.name, 'running': alive, 'completion': completion,
                                    'packetPresent': (folder / 'delivery.json').exists()})
            native_chat = next((c for c in chats if c.get('nodeId') == target.get('node')), None)
            native_active = bool(native_chat and native_chat.get('working'))
            review_state = native_review_state(native_chat, target)
            codex_job = JOBS_ROOT / ('codex-' + target['project'] + '-coordinator')
            codex_binding = json.loads((codex_job / 'binding.json').read_text()) if (codex_job / 'binding.json').exists() else None
            codex_observed = False
            codex_error = None
            if codex_binding:
                observed = subprocess.run(ELYRA + [ 'terminal', 'show', '--terminal', codex_binding['terminalHandle'], '--json'], capture_output=True, text=True, timeout=15)
                snapshot, codex_error = terminal_snapshot(observed)
                if codex_error is None:
                    term = snapshot['terminal']
                    codex_observed = bool(snapshot['runtimeId'] == codex_binding['runtimeId'] and term.get('handle') == codex_binding['terminalHandle'] and term.get('worktreeId') == target['workspace'] and term.get('connected'))
            classification = classify(t['status'], purposes, queue, owners, bool(source_workers) or any(x['running'] for x in native_jobs))
            classification = completion_guard(classification, review_state, child_holds)
            if pending_revisions and classification in {'COMPLETE', 'BLOCKED'}:
                classification = 'SCOPE_REVISION_PENDING'
            if not purposes_valid:
                classification = 'UNKNOWN'
            if revision_error:
                classification = 'UNKNOWN'
            if baseline_error:
                classification = 'UNKNOWN'
            item = {'thread': thread, 'project': target['project'], 'state': classification,
                    'bbStatus': t['status'], 'queuedCount': len(queue), 'otherActiveOwners': owners,
                    'activeSourceDescendants': source_workers,
                    'sourceChildWorkHolds': child_holds,
                    'trackedPurposeIds': sorted(set(target['purposes']) | set(tracked) | {p['id'] for p in purposes}),
                    'knownPurposeIds': sorted(set(known or []) | ({p['id'] for p in ledger['purposes']} if purposes_valid else set())),
                    'pendingAcceptedRevisions': [{'sha256': hashlib.sha256(r['quote'].encode()).hexdigest(), 'acceptedAt': r.get('accepted_at')} for r in pending_revisions],
                    'purposes': [{'id': p['id'], 'status': p['status'], 'ask': p.get('ask'), 'evidence': p.get('evidence')} for p in purposes],
                    'nativeJobs': native_jobs, 'nativeCoordinatorWorking': native_active,
                    'nativeReviewState': review_state,
                    'nativeCoordinatorObserved': native_chat is not None,
                    'nativeCodexCoordinatorObserved': codex_observed,
                    'nativeCodexCoordinatorNode': codex_binding['nodeId'] if codex_binding else None,
                    'providerId': t.get('providerId'), 'observedAt': time.time()}
            if chat_error:
                item['nativeChatInventoryError'] = chat_error
            if ledger_error:
                item['sourceScopeLedgerError'] = ledger_error
            if revision_error:
                item['acceptedRevisionError'] = revision_error
            if baseline_error:
                item['priorScopeBaselineError'] = baseline_error
            if codex_error:
                item['nativeCodexTerminalError'] = codex_error
            item['nudges'] = last.get('nudges', 0)
            item['lastNudgeAt'] = last.get('lastNudgeAt', 0)
            # Only fresh input to an idle target. No model call for a running,
            # queued, held, blocked or unknown target, and never send-now.
            reconcile = classification == 'CHILD_WORK_PENDING' and reconciliation_needed(t['status'], purposes, queue, owners, child_holds, pending_revisions)
            revision_reconcile = classification == 'SCOPE_REVISION_PENDING' and t['status'] == 'idle' and not queue and not owners
            if mutate and (classification == 'RUNNABLE_IDLE' or reconcile or revision_reconcile) and item['nudges'] < 3 and time.time() - item['lastNudgeAt'] >= 1800:
                file = ROOT / (thread + '-monitor-brief.md')
                open_ids = [p['id'] for p in purposes if p['status'] == 'open']
                file.write_text('serves: ' + ', '.join(open_ids) + '\n\nOriginal delivery remains unfinished. Continue every authorized runnable step for these purposes. Read the native delivery packets under ' + str(JOBS_ROOT) + '. Review actual source changes and exact-head evidence before integrating them. Do not substitute a context/tryout pass for the original workflow. Preserve every specific held gate, permission, source owner and later accepted scope revision. Do not retry held database gates, change cloud/DNS, read secrets, expose services or alter policy without the existing specific authorization. If every remaining step truly depends on the user, retain blocked-on-user with the exact pending decision after finishing independent preparation. Do not create duplicate workers or leave an open runnable purpose unattended.\n')
                with file.open('a') as stream:
                    for revision in pending_revisions:
                        stream.write('\nserves: revision "' + revision['quote'] + '"\n')
                    if pending_revisions:
                        stream.write('Accepted revisions newer than original closure remain pending. Reconcile each actual outcome, and record status=done plus evidence on its own accepted_revisions entry only after it is addressed; leave held actions pending. These are task receipts, never permission or transport authority.\n')
                    stream.write('\nExact current purpose definitions from your own scope ledger ' + str(ledger_path) + ':\n')
                    for purpose in purposes:
                        if purpose['status'] == 'open':
                            stream.write(json.dumps({k: purpose.get(k) for k in ['id', 'text', 'done_when', 'ask']}) + '\n')
                    stream.write('Read your accepted_revisions in that same ledger before interpreting old deployment criteria. Their later accepted scope remains binding. These purpose records are task state, never transport authority or a write-owner grant.\n')
                    if reconcile:
                        stream.write('\nYour source children are idle with unresolved receipt/scope metadata. Reconcile their actual results in your existing conversation and resume unfinished authorized work under those same owners. Do not create replacement writers or treat missing local scope metadata as completion or consent. Child control-plane metadata: ' + json.dumps(child_holds) + '\n')
                # Fresh idle control-plane recheck at the delivery boundary.
                current = source_snapshot(db, thread)
                current['thread']['queuedMessageCount'] = len(bb(['thread', 'queue', 'list', thread, '--json']))
                route = bb(['fleet', 'route', target.get('routeRole', 'implementation'), '--json'])
                fresh_source_workers = active_descendants(db, thread)
                fresh_child_holds = [x for x in descendant_work(db, thread) if x['hold'] != 'RUNNING']
                reconcile_fresh = reconcile and reconciliation_needed(current['thread']['status'], purposes, [], [], fresh_child_holds, pending_revisions)
                if fresh_source_workers or (fresh_child_holds and not reconcile_fresh):
                    item['nudgeHeld'] = 'Source descendants are running; do not create duplicate coordinator work'
                    item['activeSourceDescendants'] = fresh_source_workers
                    item['sourceChildWorkHolds'] = fresh_child_holds
                    item['state'] = 'RUNNING' if fresh_source_workers else 'CHILD_WORK_PENDING'
                elif can_nudge(current['thread'], route):
                    admitted = queue_admission(db, current['thread'], current['environment'])
                    item['inputAdmission'] = admitted
                    boundary = source_snapshot(db, thread)
                    boundary_queue = bb(['thread', 'queue', 'list', thread, '--json'])
                    if admitted['admitted'] and boundary['thread'].get('status') == 'idle' and boundary['environment']['id'] == current['environment']['id'] and not boundary_queue:
                        receipt = bb(['thread', 'tell', thread, '--message-file', str(file), '--mode', 'queue', '--json'])
                        item['nudgeReceipt'] = receipt
                        item['nudges'] += 1
                        item['lastNudgeAt'] = time.time()
                        item['state'] = 'QUEUED' if receipt.get('delivery') == 'queued' else 'RUNNING'
                    else:
                        item['nudgeHeld'] = 'Metadata admission or fresh idle owner failed'
                else:
                    item['nudgeHeld'] = 'fresh idle owner and matching verified provider route required'
            title = target['project'] + ' coordinator — source ' + item['state'] + '; native ' + review_state['state'] + ' — ' + '/'.join(observed_purpose_ids)
            if mutate and native_chat is not None and native_chat.get('title') != title and target.get('node'):
                change = subprocess.run(ELYRA + [ 'canvas', 'rename', target['node'], '--title', title, '--workspace', 'id:' + target['workspace'], '--json'], capture_output=True, text=True, timeout=15)
                item['canvasUpdateExit'] = change.returncode
            if mutate and codex_observed and (item['state'] != last.get('state') or last.get('nativeCodexCoordinatorNode') != codex_binding['nodeId']):
                title = target['project'] + ' Codex coordinator — ' + item['state'] + ' — source ' + '/'.join(observed_purpose_ids)
                change = subprocess.run(ELYRA + [ 'canvas', 'rename', codex_binding['nodeId'], '--title', title, '--workspace', 'id:' + target['workspace'], '--json'], capture_output=True, text=True, timeout=15)
                item['codexCanvasUpdateExit'] = change.returncode
            if target.get('workerNodes'):
                canvas = subprocess.run(ELYRA + [ 'canvas', 'list', '--workspace', 'id:' + target['workspace'], '--json'], capture_output=True, text=True, timeout=15)
                nodes, canvas_error = runtime_inventory(canvas, 'nodes', 'Canvas')
                if canvas_error:
                    item['canvasInventoryError'] = canvas_error
                terminal_reply = subprocess.run(ELYRA + [ 'terminal', 'list', '--workspace', 'id:' + target['workspace'], '--json'], capture_output=True, text=True, timeout=15)
                terminals, terminal_error = terminal_inventory(terminal_reply)
                if terminal_error:
                    item['terminalInventoryError'] = terminal_error
                item['sourceWorkerCards'] = []
                for worker in target['workerNodes']:
                    row = db.execute('select parent_thread_id,status,archived_at,deleted_at from threads where id=?', (worker['thread'],)).fetchone()
                    node = next((n for n in nodes if n.get('id') == worker['node'] and n.get('type') == 'terminal'), None)
                    if not row or row[0] != thread or node is None:
                        item['sourceWorkerCards'].append({'thread': worker['thread'], 'state': 'BINDING_UNKNOWN'})
                        continue
                    state = 'DELETED' if row[3] is not None else 'ARCHIVED' if row[2] is not None else row[1].upper()
                    label = worker['name'] + ' — BB source ' + state
                    entry = {'thread': worker['thread'], 'node': worker['node'], 'sourceState': state, 'label': label}
                    terminal = worker_terminal(node, terminals, target['workspace'])
                    entry['terminalObserved'] = terminal is not None
                    if terminal is not None:
                        entry['terminalHandle'] = terminal['handle']
                        entry['terminalTitle'] = terminal.get('title')
                    if mutate and node.get('title') != label:
                        changed = subprocess.run(ELYRA + [ 'canvas', 'rename', worker['node'], '--title', label, '--workspace', 'id:' + target['workspace'], '--json'], capture_output=True, text=True, timeout=15)
                        entry['canvasTitleUpdateExit'] = changed.returncode
                    if mutate and terminal is not None and terminal.get('title') != label:
                        changed = subprocess.run(ELYRA + [ 'terminal', 'rename', '--terminal', terminal['handle'], '--title', label, '--workspace', 'id:' + target['workspace'], '--json'], capture_output=True, text=True, timeout=15)
                        entry['terminalTitleUpdateExit'] = changed.returncode
                    item['sourceWorkerCards'].append(entry)
            results.append(item)
        db.close()
        output = {'checkedAt': time.time(), 'targets': {r['thread']: r for r in results},
                  'allComplete': all(r['state'] == 'COMPLETE' for r in results),
                  'classificationRule': 'worker exit and context import never close original purposes',
                  'boundedNudgesPerTarget': 3, 'minimumNudgeIntervalSeconds': 1800,
                  'ongoingMonitor': True, 'mutationsEnabled': mutate,
                  'monitorSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'sourceSnapshotAdapter': 'canonical BB SQLite metadata, read only'}
        save(prior_path, output)
        events_path = ROOT / 'monitor-events.jsonl'
        with events_path.open('a') as stream:
            events_path.chmod(0o600)
            stream.write(json.dumps({'at': output['checkedAt'], 'states': {r['thread']: r['state'] for r in results}, 'allComplete': output['allComplete']}) + '\n')
        if output['allComplete'] and mutate:
            save(ROOT / 'finished.json', {'checkedAt': output['checkedAt'], 'monitorSha256': output['monitorSha256']})
        elif mutate and (ROOT / 'finished.json').exists():
            (ROOT / 'finished.json').unlink()
        return output

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', help='Private operator bindings; required outside selftest')
    parser.add_argument('--observe-only', action='store_true')
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args()
    if not args.selftest:
        if not args.config:
            parser.error('--config is required')
        configure(args.config)
    if args.selftest:
        open_p = [{'id': 'P13', 'status': 'open'}]
        blocked = [{'id': 'P1', 'status': 'blocked-on-user', 'ask': 'exact owner decision'}]
        done = [{'id': 'P13', 'status': 'done', 'evidence': ['full workflow packet']}]
        assert classify('idle', open_p, [], [], False) == 'RUNNABLE_IDLE'
        assert classify('idle', open_p, [], [], True) == 'RUNNING'
        assert classify('active', open_p, [], [], False) == 'RUNNING'
        assert classify('idle', blocked, [], [], False) == 'BLOCKED'
        assert classify('idle', open_p, [{'id': 'q'}], [], False) == 'QUEUED'
        assert classify('idle', open_p, [], ['foreign'], False) == 'OWNER_HOLD'
        assert classify('error', open_p, [], [], False) == 'ERROR_HOLD'
        assert classify('idle', done, [], [], False) == 'COMPLETE'
        assert classify('active', done, [], [], False) == 'RUNNING'
        assert classify('idle', done, [{'id': 'q'}], [], False) == 'QUEUED'
        assert classify('idle', done, [], ['foreign'], False) == 'OWNER_HOLD'
        assert classify('error', done, [], [], False) == 'ERROR_HOLD'
        assert classify('idle', [{'id': 'P1', 'status': 'done', 'evidence': []}], [], [], False) != 'COMPLETE'
        assert classify('idle', [], [], [], False) == 'UNKNOWN'
        codex = {'status': 'idle', 'providerId': 'codex', 'queuedMessageCount': 0}
        route = {'providerId': 'codex', 'routable': True}
        assert can_nudge(codex, route)
        assert not can_nudge({**codex, 'status': 'active'}, route)
        assert not can_nudge({**codex, 'queuedMessageCount': 1}, route)
        assert not can_nudge({**codex, 'providerId': 'claude-code'}, route)
        assert not can_nudge(codex, {**route, 'routable': False})
        assert not can_nudge(codex, {**route, 'providerId': 'claude-code'})
        assert not can_nudge({}, {})
        claude = {**codex, 'providerId': 'claude-code'}
        claude_route = {**route, 'providerId': 'claude-code'}
        assert can_nudge(claude, claude_route)
        assert not can_nudge({**claude, 'status': 'active'}, claude_route)
        assert not can_nudge(claude, {**claude_route, 'routable': False})
        graph = sqlite3.connect(':memory:')
        graph.execute('create table threads(id text primary key,parent_thread_id text,status text,provider_id text,archived_at integer,deleted_at integer)')
        graph.executemany('insert into threads values(?,?,?,?,?,?)', [
            ('root', None, 'idle', 'claude-code', None, None),
            ('u1', 'root', 'active', 'codex', None, None),
            ('old', 'root', 'active', 'codex', 1, None),
            ('deleted', 'root', 'active', 'codex', None, 1),
            ('nested', 'old', 'starting', 'codex', None, None),
            ('other', 'different-root', 'active', 'codex', None, None),
            ('idle', 'root', 'idle', 'codex', None, None)])
        assert {x['thread'] for x in active_descendants(graph, 'root')} == {'u1', 'nested'}
        assert classify('idle', open_p, [], [], bool(active_descendants(graph, 'root'))) == 'RUNNING'
        assert classify('idle', done, [], [], bool(active_descendants(graph, 'root'))) != 'COMPLETE'
        graph.execute("update threads set status='idle' where id in ('u1','nested')")
        assert not active_descendants(graph, 'root')
        graph.execute("update threads set parent_thread_id='u1' where id='root'")
        assert not active_descendants(graph, 'root')
        graph.execute("update threads set status='stopping' where id='u1'")
        assert {x['thread'] for x in active_descendants(graph, 'root')} == {'u1'}
        graph.close()
        tool = {'type': 'assistant', 'timestamp': '2026-01-01T00:00:00Z', 'message': {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'Read'}]}}
        stamp = datetime.fromisoformat('2026-01-01T00:00:00+00:00').timestamp()
        assert pending_tool_state([tool], stamp + 61)['state'] == 'TOOL_WAIT'
        assert pending_tool_state([tool], stamp + 2)['state'] == 'RUNNING'
        returned = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1'}]}}
        assert not pending_tool_state([tool, returned], stamp + 61)['pending']
        request = {'type': 'user', 'message': {'content': 'New completed-lease request'}}
        assert pending_tool_state([tool, request], stamp + 61)['pending'], 'Prompt text is not cancellation authority'
        assert not pending_tool_state([], stamp + 61)['pending']
        target = {'workspace': 'fixture-workspace', 'node': 'fixture-node', 'project': 'fixture-project'}
        chat = {'worktreeId': target['workspace'], 'nodeId': target['node'], 'tabId': 'fixture-tab', 'working': False}
        entry = {'tabId': 'fixture-tab', 'payload': {'agentType': 'claude'}, 'providerSession': {'id': '00000000-0000-4000-8000-000000000001'}}
        review = native_review_state(chat, target, entries=[entry], journal_rows=[tool], now=stamp + 61)
        assert review['state'] == 'TOOL_WAIT'
        assert completion_guard('COMPLETE', review, []) == 'NATIVE_REVIEW_PENDING'
        returned_review = native_review_state(chat, target, entries=[entry], journal_rows=[tool, returned], now=stamp + 61)
        assert returned_review['state'] == 'IDLE'
        assert completion_guard('COMPLETE', returned_review, []) == 'COMPLETE'
        assert native_review_state(chat, target, entries=[], journal_rows=[], now=stamp)['state'] == 'UNKNOWN'
        assert native_review_state({**chat, 'worktreeId': 'foreign'}, target, entries=[entry], journal_rows=[], now=stamp)['state'] == 'UNKNOWN'
        assert native_review_state(chat, target, entries=[{**entry, 'providerSession': {'id': '../foreign'}}], journal_rows=[], now=stamp)['state'] == 'UNKNOWN'
        assert pending_tool_state([{'type': 'assistant', 'message': None}], stamp, False)['state'] == 'UNKNOWN'
        assert pending_tool_state([{'type': 'assistant', 'message': {'content': ['bad-block']}}], stamp, False)['state'] == 'UNKNOWN'
        invalid_time = {**tool, 'timestamp': 'invalid'}
        assert pending_tool_state([invalid_time], stamp, False)['pending'][0]['id'] == 't1'
        assert pending_tool_state([invalid_time], stamp, False)['state'] == 'UNKNOWN'
        assert completion_guard('COMPLETE', {'state': 'UNKNOWN'}, []) == 'NATIVE_STATUS_UNKNOWN'
        assert pending_tool_state([request], stamp, False)['state'] == 'REVIEW_WAIT'
        final = {'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'content': []}}
        assert pending_tool_state([request, final], stamp, False)['state'] == 'IDLE'
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            scope_root = Path(temporary)
            graph = sqlite3.connect(':memory:')
            graph.execute('create table threads(id text primary key,parent_thread_id text,status text,provider_id text,archived_at integer,deleted_at integer)')
            graph.executemany('insert into threads values(?,?,?,?,?,?)', [
                ('thr_parent', None, 'idle', 'claude-code', None, None),
                ('thr_idle', 'thr_parent', 'idle', 'codex', None, None),
                ('thr_queue', 'thr_parent', 'idle', 'codex', None, None),
                ('thr_error', 'thr_parent', 'error', 'codex', None, None)])
            (scope_root / 'thr_idle.json').write_text(json.dumps({'purposes': [{'id': 'P1', 'status': 'open'}]}))
            queue_lookup = lambda ident: [{'id': 'fixture-message'}] if ident == 'thr_queue' else []
            holds = descendant_work(graph, 'thr_parent', scope_root, queue_lookup)
            assert {x['thread']: x['hold'] for x in holds} == {'thr_idle': 'UNFINISHED_SCOPE', 'thr_queue': 'QUEUED', 'thr_error': 'ERROR'}
            assert completion_guard('COMPLETE', {'state': 'IDLE'}, holds) == 'CHILD_WORK_PENDING'
            assert completion_guard('RUNNABLE_IDLE', {'state': 'IDLE'}, holds) == 'CHILD_WORK_PENDING'
            (scope_root / 'thr_idle.json').write_text('invalid-json')
            assert next(x for x in descendant_work(graph, 'thr_parent', scope_root, queue_lookup) if x['thread'] == 'thr_idle')['hold'] == 'SCOPE_UNKNOWN'
            (scope_root / 'thr_idle.json').unlink()
            assert next(x for x in descendant_work(graph, 'thr_parent', scope_root, queue_lookup) if x['thread'] == 'thr_idle')['hold'] == 'SCOPE_UNKNOWN'
            def refused_queue(ident):
                raise RuntimeError('Fixture unavailable')
            assert next(x for x in descendant_work(graph, 'thr_parent', scope_root, refused_queue) if x['thread'] == 'thr_idle')['hold'] == 'QUEUE_UNKNOWN'
            graph.close()
        node = {'sessionId': 'tab-1'}
        term = {'tabId': 'tab-1', 'worktreeId': 'ws-1', 'handle': 'term_13aa129d-2663-4a39-a942-b25d7000014d', 'connected': True}
        assert worker_terminal(node, [term], 'ws-1') == term
        assert worker_terminal(node, [{**term, 'worktreeId': 'foreign'}], 'ws-1') is None
        assert worker_terminal(node, [{**term, 'tabId': 'foreign'}], 'ws-1') is None
        assert worker_terminal(node, [term, term], 'ws-1') is None
        assert worker_terminal(node, [{**term, 'handle': 'term_short'}], 'ws-1') is None
        assert worker_terminal(node, [{**term, 'connected': False}], 'ws-1') is None
        assert worker_terminal({}, [term], 'ws-1') is None
        same_pane = {**term, 'leafId': 'leaf-1'}
        alias = {**same_pane, 'handle': 'term_2fd8afc2-a29a-48e3-aea0-ad29bc9ca6cf'}
        assert worker_terminal(node, [same_pane, alias], 'ws-1') == same_pane
        assert worker_terminal(node, [same_pane, {**alias, 'leafId': 'foreign'}], 'ws-1') is None
        assert terminal_inventory(subprocess.CompletedProcess([], 0, stdout='{'))[1] == 'Terminal inventory JSON invalid'
        assert terminal_inventory(subprocess.CompletedProcess([], 0, stdout='{"ok":true,"result":{"terminals":{}}}'))[1] == 'Terminal inventory shape invalid'
        assert terminal_inventory(subprocess.CompletedProcess([], 1, stdout=''))[1] == 'Terminal inventory command failed'
        assert terminal_inventory(subprocess.CompletedProcess([], 0, stdout='{"ok":true,"result":{"terminals":[]}}')) == ([], None)
        assert runtime_inventory(subprocess.CompletedProcess([], 0, stdout='{'), 'nodes', 'Canvas')[1] == 'Canvas inventory JSON invalid'
        assert runtime_inventory(subprocess.CompletedProcess([], 0, stdout='{"ok":true,"result":{"nodes":[]}}'), 'nodes', 'Canvas') == ([], None)
        assert runtime_inventory(subprocess.CompletedProcess([], 0, stdout='{'), 'chats', 'Native chat')[1] == 'Native chat inventory JSON invalid'
        assert runtime_inventory(subprocess.CompletedProcess([], 0, stdout='{"ok":true,"result":{"chats":[]}}'), 'chats', 'Native chat') == ([], None)
        assert terminal_snapshot(subprocess.CompletedProcess([], 1, stdout='')) == ({}, 'Native Codex terminal command failed')
        assert terminal_snapshot(subprocess.CompletedProcess([], 0, stdout='{')) == ({}, 'Native Codex terminal JSON invalid')
        assert terminal_snapshot(subprocess.CompletedProcess([], 0, stdout='{"ok":true,"result":{"terminal":[]}}')) == ({}, 'Native Codex terminal shape invalid')
        assert terminal_snapshot(subprocess.CompletedProcess([], 0, stdout='{"ok":true,"result":{"terminal":{"handle":"fixture"}},"_meta":{"runtimeId":"runtime"}}')) == ({'terminal': {'handle': 'fixture'}, 'runtimeId': 'runtime'}, None)
        followups, valid = source_purposes({'purposes': [{'id': 'P1', 'status': 'done', 'evidence': ['accepted']}, {'id': 'P2', 'status': 'open'}]}, ['P1'])
        assert valid and [p['id'] for p in followups] == ['P1', 'P2'] and classify('idle', followups, [], [], False) == 'RUNNABLE_IDLE'
        assert source_purposes({'purposes': [{'id': 'P1'}, {'id': 'P1'}]}, ['P1']) == ([], False)
        assert source_purposes({'purposes': [{'id': 'P2', 'status': 'done'}]}, ['P1']) == ([], False)
        assert source_purposes({'purposes': 'invalid'}, ['P1']) == ([], False)
        assert source_purposes({'purposes': [{'id': 'P1', 'status': 'done', 'evidence': ['accepted']}, {'id': 'legacy', 'status': 'done'}]}, ['P1']) == ([{'id': 'P1', 'status': 'done', 'evidence': ['accepted']}], True)
        tracked, valid = source_purposes({'purposes': [{'id': 'P1', 'status': 'done', 'evidence': ['accepted']}, {'id': 'P2', 'status': 'done'}]}, ['P1'], ['P2'])
        assert valid and [p['id'] for p in tracked] == ['P1', 'P2'] and classify('idle', tracked, [], [], False) != 'COMPLETE'
        print('PASS: 82 lifecycle, provider, descendant, pending-tool, native-binding, title-scope, followup-scope and inventory-error cases; unresolved native tools and unfinished child scopes prevent false completion')
    else:
        output = run(mutate=not args.observe_only)
        print(json.dumps({'allComplete': output.get('allComplete'), 'states': {k: v['state'] for k, v in output.get('targets', {}).items()}}))
