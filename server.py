#!/usr/bin/env python3
"""Business-in-a-Box local backend starter (Python standard library only).
Run: python3 server.py ; open http://127.0.0.1:8080
For production, replace the development server and configure HTTPS, backups and managed secrets.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import hashlib, hmac, json, os, secrets, sqlite3, time, re

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'business_in_a_box.sqlite3'
HOST, PORT = '127.0.0.1', int(os.environ.get('PORT', '8080'))
SESSION_TTL = 60 * 60 * 24 * 14

def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL, salt TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workspaces (
          id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
          name TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workspace_state (
          workspace_id INTEGER PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
          state_json TEXT NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          expires_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
        ''')

def json_bytes(obj): return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    return digest, salt

def session_token(user_id):
    token = secrets.token_urlsafe(32)
    with db() as c:
        c.execute('INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)',
                  (hashlib.sha256(token.encode()).hexdigest(), user_id, int(time.time()) + SESSION_TTL))
    return token

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(ROOT), **kwargs)
    def log_message(self, fmt, *args): print('[%s] %s' % (self.log_date_time_string(), fmt % args))
    def send_json(self, status, payload, cookie=None, clear_cookie=False):
        body = json_bytes(payload); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Content-Security-Policy', "default-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; script-src 'self'; img-src 'self' data:; connect-src 'self'")
        if cookie: self.send_header('Set-Cookie', f'biab_session={cookie}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}')
        if clear_cookie: self.send_header('Set-Cookie','biab_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
        self.end_headers(); self.wfile.write(body)
    def read_json(self):
        try:
            n = int(self.headers.get('Content-Length','0'))
            if n > 2_000_000: raise ValueError('Request too large')
            return json.loads(self.rfile.read(n) or b'{}')
        except Exception: raise ValueError('Invalid JSON request')
    def user(self):
        raw = self.headers.get('Cookie','')
        token = next((x.split('=',1)[1] for x in raw.split('; ') if x.startswith('biab_session=')), None)
        if not token: return None
        key = hashlib.sha256(token.encode()).hexdigest()
        with db() as c:
            row = c.execute('SELECT u.id,u.name,u.email,w.id AS workspace_id,w.name AS company FROM sessions s JOIN users u ON u.id=s.user_id JOIN workspaces w ON w.owner_id=u.id WHERE s.token_hash=? AND s.expires_at>?',(key,int(time.time()))).fetchone()
        return dict(row) if row else None
    def do_GET(self):
        path=urlparse(self.path).path
        if path == '/api/me':
            u=self.user(); self.send_json(200, {'user': ({'id':u['id'],'name':u['name'],'email':u['email'],'company':u['company']} if u else None)}); return
        if path == '/api/state':
            u=self.user()
            if not u: self.send_json(401,{'error':'Sign in required'}); return
            with db() as c: row=c.execute('SELECT state_json,updated_at FROM workspace_state WHERE workspace_id=?',(u['workspace_id'],)).fetchone()
            self.send_json(200, {'state':json.loads(row['state_json']) if row else None,'updatedAt':row['updated_at'] if row else None}); return
        return super().do_GET()
    def do_POST(self):
        path=urlparse(self.path).path
        try: data=self.read_json()
        except ValueError as e: self.send_json(400,{'error':str(e)}); return
        if path == '/api/register':
            name=str(data.get('name','')).strip()[:100]; company=str(data.get('company','')).strip()[:140]; email=str(data.get('email','')).strip().lower()[:254]; password=str(data.get('password',''))
            if not name or not company or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): self.send_json(400,{'error':'Enter your name, business name and a valid email.'}); return
            if len(password)<10: self.send_json(400,{'error':'Use a password with at least 10 characters.'}); return
            digest,salt=hash_password(password)
            try:
                with db() as c:
                    cur=c.execute('INSERT INTO users(name,email,password_hash,salt,created_at) VALUES(?,?,?,?,?)',(name,email,digest,salt,int(time.time())))
                    uid=cur.lastrowid; cur=c.execute('INSERT INTO workspaces(owner_id,name,created_at) VALUES(?,?,?)',(uid,company,int(time.time())))
            except sqlite3.IntegrityError: self.send_json(409,{'error':'An account with this email already exists. Sign in instead.'}); return
            token=session_token(uid); self.send_json(201,{'user':{'id':uid,'name':name,'email':email,'company':company}},cookie=token); return
        if path == '/api/login':
            email=str(data.get('email','')).strip().lower(); password=str(data.get('password',''))
            with db() as c: row=c.execute('SELECT id,name,email,password_hash,salt FROM users WHERE email=?',(email,)).fetchone()
            if not row or not hmac.compare_digest(hash_password(password,row['salt'])[0],row['password_hash']): self.send_json(401,{'error':'Email or password is incorrect.'}); return
            token=session_token(row['id']); u=self.user() # cookie is not on this request yet; return safe account info directly
            with db() as c: w=c.execute('SELECT name FROM workspaces WHERE owner_id=?',(row['id'],)).fetchone()
            self.send_json(200,{'user':{'id':row['id'],'name':row['name'],'email':row['email'],'company':w['name'] if w else ''}},cookie=token); return
        if path == '/api/logout':
            raw=self.headers.get('Cookie',''); token=next((x.split('=',1)[1] for x in raw.split('; ') if x.startswith('biab_session=')),None)
            if token:
                with db() as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
            self.send_json(200,{'ok':True},clear_cookie=True); return
        self.send_json(404,{'error':'Not found'})
    def do_PUT(self):
        if urlparse(self.path).path != '/api/state': self.send_json(404,{'error':'Not found'}); return
        u=self.user()
        if not u: self.send_json(401,{'error':'Sign in required'}); return
        try: state=self.read_json()
        except ValueError as e: self.send_json(400,{'error':str(e)}); return
        if not isinstance(state,dict): self.send_json(400,{'error':'State must be an object'}); return
        # Workspace ownership is resolved from the authenticated session; clients cannot choose another workspace.
        encoded=json.dumps(state,ensure_ascii=False,separators=(',',':'))
        with db() as c:
            c.execute('INSERT INTO workspace_state(workspace_id,state_json,updated_at) VALUES(?,?,?) ON CONFLICT(workspace_id) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at',(u['workspace_id'],encoded,int(time.time())))
        self.send_json(200,{'ok':True,'updatedAt':int(time.time())})
    def end_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','strict-origin-when-cross-origin')
        super().end_headers()

if __name__ == '__main__':
    init_db()
    print(f'Business-in-a-Box backend running at http://{HOST}:{PORT}')
    print('Development server only. Do not expose publicly without production hardening and HTTPS.')
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
