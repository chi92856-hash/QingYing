"""Focused offline checks; no browser, login, network, or user data required."""
import ast
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'source'))
from common import LocalRPC, load_settings, save_settings, saved_files_exist
from facebook_history import FacebookHistory


def collector_history_class():
    # Isolate the database class from optional network and media dependencies.
    tree = ast.parse((ROOT / 'source' / 'collector.py').read_text('utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'History')
    namespace = dict(Path=Path, sqlite3=sqlite3, json=json, time=time,
                     contextmanager=contextmanager, saved_files_exist=saved_files_exist)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'collector.History', 'exec'), namespace)
    return namespace['History']


def check_settings(folder):
    path = folder / 'settings.json'
    for document in ('[]', 'null', '123', '"text"', '{broken'):
        path.write_text(document, encoding='utf-8')
        assert load_settings(path) == {}
    path.unlink()
    assert load_settings(path) == {}
    expected = {'folder': '中文目录', 'mute': True}
    save_settings(path, expected)
    assert load_settings(path) == expected
    # Serialization failure must preserve the previous file and clean temporary files.
    try:
        save_settings(path, {'invalid': object()})
    except TypeError:
        pass
    else:
        raise AssertionError('Invalid setting was accepted')
    assert load_settings(path) == expected
    assert not list(folder.glob('settings.json.*.tmp'))


def check_histories(folder):
    history = collector_history_class()(folder / 'xhs.db')
    candidate = type('Candidate', (), dict(identifier='note', title='测试作品'))()
    media = folder / 'photo.jpg'
    media.write_bytes(b'media')
    history.mark(candidate, '图片', [media])
    assert history.contains('note')
    media.unlink()
    assert not history.contains('note')
    media.write_bytes(b'')
    assert not history.contains('note')
    media.write_bytes(b'redownloaded')
    history.mark(candidate, '图片', [media])
    assert history.contains('note') and history.count() == 1
    with history.connect() as db:
        db.execute('UPDATE completed SET files=?', ('{"bad":"shape"}',))
    assert not history.contains('note')
    try:
        db.execute('SELECT 1')
    except sqlite3.ProgrammingError:
        pass
    else:
        raise AssertionError('XHS connection was not closed')
    facebook = FacebookHistory(folder / 'facebook.db')
    item = dict(id='photo', kind='image', url='https://www.facebook.com/photo')
    facebook.discover('profile', folder, item, 'photos')
    facebook.mark('profile', folder, 'photo', [media])
    assert facebook.completed('profile', folder, 'photo')
    media.unlink()
    assert not facebook.completed('profile', folder, 'photo')
    assert facebook.pending('profile', folder, ['photos']) == [dict(item, title='')]
    with facebook.connect() as db:
        db.execute('SELECT 1')
    try:
        db.execute('SELECT 1')
    except sqlite3.ProgrammingError:
        pass
    else:
        raise AssertionError('Facebook connection was not closed')
    # Windows rejects this if a database handle is still open.
    history.path.unlink()
    facebook.path.unlink()


def check_rpc():
    class Connection:
        def __init__(self):
            self.sent = []
            self.replies = []
        def send(self, message):
            self.sent.append(message)
            if message == 'next':
                self.replies.append('next reply')
        def poll(self, timeout):
            return bool(self.replies)
        def recv(self):
            return self.replies.pop(0)
    connection = Connection()
    rpc = LocalRPC(connection, 0, 'timeout')
    for message in ('slow', 'must not send'):
        try:
            rpc.request(message)
        except TimeoutError:
            pass
        else:
            raise AssertionError('Expected timeout')
    assert connection.sent == ['slow']
    connection.replies.append('late reply')
    assert rpc.request('next') == 'next reply'
    assert connection.sent == ['slow', 'next']
    assert not rpc.waiting


def main():
    for path in (ROOT / 'source').glob('*.py'):
        compile(path.read_text('utf-8'), str(path), 'exec')
    print('PASS: all source files compile')
    with tempfile.TemporaryDirectory(prefix='.qingying-check-', dir=ROOT) as directory:
        folder = Path(directory)
        check_settings(folder)
        print('PASS: invalid settings, atomic save and failure cleanup')
        check_histories(folder)
        print('PASS: deleted/empty media, redownload, closed database handles')
    check_rpc()
    print('PASS: late responses cannot be mistaken for new responses')


if __name__ == '__main__':
    main()
