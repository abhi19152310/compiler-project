"""JSON/SQLite persistence of validated compiler IR, with optimistic revisions."""

from dataclasses import asdict
import json
from pathlib import Path
import sqlite3

from .model import CompilationResult, Diagnostic, Element, PageNode, PageTree, Sentence, Statement


class StaleRevision(ValueError):
    pass


def restore(data):
    def node(value):
        return PageNode(value['element_id'], value['direction'], [node(c) for c in value['children']])
    result = CompilationResult(
        sentences=[Sentence(**v) for v in data['sentences']], tokens=data['tokens'],
        ast=[Statement(**v) for v in data['ast']], symbols=[Element(**v) for v in data['symbols']],
        diagnostics=[Diagnostic(**v) for v in data['diagnostics']], html=data['html'], css=data['css'],
        page_properties=data['page_properties'], focus_id=data.get('focus_id'), focus_explicit=data.get('focus_explicit', False), interpretations=data.get('interpretations', []))
    tree = data.get('page_tree')
    if tree:
        result.page_tree = PageTree(tree['title'], [node(n) for n in tree['children']], tree.get('properties', {}))
    return result


class WorkspaceStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self, key):
        if not self.path.exists():
            return None
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT revision, payload FROM workspaces WHERE id = ?', (key,)).fetchone()
        if not row:
            return None
        payload = json.loads(row[1])
        payload['result'] = restore(payload['result'])
        return {'revision': row[0], **payload}

    def save(self, key, *, expected, result, source, build_id):
        if not result.success:
            raise ValueError('Only successful compiler results can be saved.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({'result': asdict(result), 'source': source, 'build_id': build_id}, ensure_ascii=True)
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM workspaces WHERE id = ?', (key,)).fetchone()
            current = row[0] if row else 0
            if current != expected:
                raise StaleRevision('This page changed in another tab. Reload before applying your instruction.')
            db.execute('INSERT INTO workspaces VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, payload=excluded.payload',
                       (key, current + 1, payload))
        return current + 1
