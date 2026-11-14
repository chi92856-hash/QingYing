"""Durable Facebook work queue, scoped to a chosen destination directory."""
import json
import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager
from common import saved_files_exist


class FacebookHistory:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS media (
                profile TEXT NOT NULL, destination TEXT NOT NULL, identifier TEXT NOT NULL,
                kind TEXT NOT NULL, page_url TEXT NOT NULL, title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', files TEXT NOT NULL DEFAULT '[]',
                error TEXT NOT NULL DEFAULT '', updated REAL NOT NULL,
                PRIMARY KEY(profile,destination,identifier))''')
            db.execute('''CREATE TABLE IF NOT EXISTS media_sources (
                profile TEXT NOT NULL,destination TEXT NOT NULL,identifier TEXT NOT NULL,category TEXT NOT NULL,
                PRIMARY KEY(profile,destination,identifier,category))''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def destination(folder):
        return str(Path(folder).resolve()).casefold()

    def discover(self, profile, folder, item, category=None):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO media(profile,destination,identifier,kind,page_url,title,updated) VALUES(?,?,?,?,?,?,?)',
                       (profile,self.destination(folder),item['id'],item['kind'],item['url'],item.get('title',''),time.time()))
            if category:
                db.execute('INSERT OR IGNORE INTO media_sources VALUES(?,?,?,?)',
                           (profile,self.destination(folder),item['id'],category))

    def completed(self, profile, folder, identifier):
        with self.connect() as db:
            row = db.execute('SELECT status,files FROM media WHERE profile=? AND destination=? AND identifier=?',
                             (profile,self.destination(folder),identifier)).fetchone()
        if not row or row[0] != 'done':
            return False
        return saved_files_exist(row[1])

    def mark(self, profile, folder, identifier, files=(), error=''):
        with self.connect() as db:
            db.execute('UPDATE media SET status=?,files=?,error=?,updated=? WHERE profile=? AND destination=? AND identifier=?',
                       ('failed' if error else 'done',json.dumps([str(Path(p).resolve()) for p in files],ensure_ascii=False),
                        str(error)[:700],time.time(),profile,self.destination(folder),identifier))

    def pending(self, profile, folder, categories=None):
        with self.connect() as db:
            if categories is None:
                rows=db.execute('SELECT identifier,kind,page_url,title FROM media WHERE profile=? AND destination=? ORDER BY updated',
                                (profile,self.destination(folder))).fetchall()
            elif not categories:return []
            else:
                marks=','.join('?' for _ in categories)
                exclude_reels=(" AND NOT EXISTS (SELECT 1 FROM media_sources r WHERE r.profile=m.profile "
                               "AND r.destination=m.destination AND r.identifier=m.identifier AND r.category='reels')"
                               if 'videos' in categories and 'reels' not in categories else '')
                rows=db.execute('SELECT m.identifier,m.kind,m.page_url,m.title FROM media m WHERE m.profile=? AND m.destination=? '
                    'AND EXISTS (SELECT 1 FROM media_sources s WHERE s.profile=m.profile AND s.destination=m.destination '
                    'AND s.identifier=m.identifier AND s.category IN ('+marks+'))'+exclude_reels+' ORDER BY m.updated',
                    (profile,self.destination(folder),*categories)).fetchall()
        return [dict(id=i,kind=k,url=u,title=t) for i,k,u,t in rows if not self.completed(profile,folder,i)]
