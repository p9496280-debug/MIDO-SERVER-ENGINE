from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import sqlite3, time, uuid, json, os, hashlib, hmac, base64, secrets, urllib.request, urllib.error, threading, socket, asyncio, urllib.parse, ipaddress

ROOT=Path(__file__).parent
STATIC=ROOT/'static'
STATIC.mkdir(exist_ok=True)
DB_PATH=Path(os.getenv('DATA_DIR', str(ROOT)))/'mido_server.db'
DB_PATH.parent.mkdir(parents=True,exist_ok=True)
SECRET=os.getenv('MIDO_SECRET_KEY','change-this-secret-before-production').encode()
ADMIN_USER=os.getenv('ADMIN_USERNAME','Mohammed')
ADMIN_PASS=os.getenv('ADMIN_PASSWORD','mohammedaaa222')
app=FastAPI(title='MIDO SERVER ENGINE',version='3.0')
app.mount('/static',StaticFiles(directory=STATIC),name='static')

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 240000).hex()
    return f'pbkdf2${salt}${digest}'

def password_verify(stored, password):
    try:
        algo, salt, digest = stored.split('$', 2)
        if algo != 'pbkdf2': return False
        check = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 240000).hex()
        return hmac.compare_digest(digest, check)
    except Exception: return False

def db():
    c=sqlite3.connect(DB_PATH,timeout=30); c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL'); return c

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS servers(id TEXT PRIMARY KEY,name TEXT NOT NULL,region TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'unknown',capacity INTEGER DEFAULT 100,monitor_url TEXT DEFAULT '',last_ping_ms REAL,last_checked INTEGER,created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'viewer',created_at INTEGER NOT NULL,enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,level TEXT,message TEXT,created_at INTEGER);
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY AUTOINCREMENT,server_id TEXT,status TEXT,ping_ms REAL,created_at INTEGER);
        CREATE TABLE IF NOT EXISTS plugins(id TEXT PRIMARY KEY,name TEXT,description TEXT,enabled INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS notices(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,message TEXT,level TEXT,created_at INTEGER,read_flag INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS match_rooms(id TEXT PRIMARY KEY, title TEXT, mode TEXT, region TEXT, server_id TEXT, creator TEXT, code TEXT, status TEXT, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS tournaments(id TEXT PRIMARY KEY,title TEXT,description TEXT,region TEXT,status TEXT,starts_at INTEGER,prize TEXT);
        CREATE TABLE IF NOT EXISTS tournament_entries(id INTEGER PRIMARY KEY AUTOINCREMENT,tournament_id TEXT,username TEXT,created_at INTEGER,UNIQUE(tournament_id,username));
        CREATE TABLE IF NOT EXISTS profiles(username TEXT PRIMARY KEY,coins INTEGER DEFAULT 500,display_name TEXT,created_at INTEGER);
        CREATE TABLE IF NOT EXISTS store_items(id TEXT PRIMARY KEY,title TEXT,description TEXT,price_coins INTEGER,category TEXT,icon TEXT,active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS store_orders(id TEXT PRIMARY KEY,username TEXT,item_id TEXT,item_title TEXT,price_coins INTEGER,created_at INTEGER);
        ''')
        # Correct old sqlite typo schema safely if first creation had the typo
        c.execute('CREATE TABLE IF NOT EXISTS plugins(id TEXT PRIMARY KEY,name TEXT,description TEXT,enabled INTEGER DEFAULT 0)')
        if c.execute('SELECT COUNT(*) FROM servers').fetchone()[0]==0:
            now=int(time.time()); c.executemany('INSERT INTO servers VALUES(?,?,?,?,?,?,?,?,?)',[
                ('eg-cairo-01','Egypt • Cairo','Cairo, EG','online',100,'',24,now,now),
                ('eu-frankfurt-01','Europe • Frankfurt','Frankfurt, DE','maintenance',100,'',92,now,now)])
        if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0:
            c.execute('INSERT INTO users VALUES(?,?,?,?,?,1)',(uuid.uuid4().hex,ADMIN_USER,password_hash(ADMIN_PASS),'admin',int(time.time())))
        plugins=[('ping-monitor','Ping Monitor','Periodic reachability and latency checks'),('history-charts','Historical Charts','Store health and latency samples'),('notifications','Alert Center','Notify when server state changes'),('backup-restore','Backup & Restore','Export/import database JSON'),('security-audit','Security Audit','Track login attempts and sensitive actions'),('plugin-market','Plugin Catalog','Install/toggle built-in plugin modules')]
        for p in plugins: c.execute('INSERT OR IGNORE INTO plugins(id,name,description,enabled) VALUES(?,?,?,1)',p)
        tournaments=[('season-cup','Season Cup','Open community cup · registration demo','Global','open',int(time.time())+86400,'500 coins'),('night-league','Night League','Weekly evening league','EU West','open',int(time.time())+172800,'300 coins')]
        for t in tournaments: c.execute('INSERT OR IGNORE INTO tournaments VALUES(?,?,?,?,?,?,?)',t)
        items=[('boost-1','XP Boost','Profile progression boost · showcase item',120,'Boosts','⚡'),('badge-elite','Elite Badge','Exclusive profile badge',250,'Cosmetics','🏅'),('theme-cyan','Cyan Arena Theme','Premium interface theme',180,'Cosmetics','🎨')]
        for it in items: c.execute('INSERT OR IGNORE INTO store_items(id,title,description,price_coins,category,icon,active) VALUES(?,?,?,?,?,?,1)',it)
init_db()

def log_event(level,msg):
    with db() as c: c.execute('INSERT INTO logs(level,message,created_at) VALUES(?,?,?)',(level,msg,int(time.time())))

def b64(x): return base64.urlsafe_b64encode(x).decode().rstrip('=')
def token_for(user):
    body=b64(json.dumps({'u':user['username'],'r':user['role'],'exp':int(time.time())+12*3600}).encode())
    sig=b64(hmac.new(SECRET,body.encode(),hashlib.sha256).digest())
    return body+'.'+sig

def current_user(authorization: str|None=Header(default=None)):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Login required')
    tok=authorization[7:]
    try:
        body,sig=tok.split('.',1); expected=b64(hmac.new(SECRET,body.encode(),hashlib.sha256).digest())
        if not hmac.compare_digest(sig,expected): raise ValueError()
        data=json.loads(base64.urlsafe_b64decode(body+'==='))
        if data['exp']<time.time(): raise ValueError()
        with db() as c: row=c.execute('SELECT enabled,role FROM users WHERE username=?',(data['u'],)).fetchone()
        if not row or not row['enabled']: raise ValueError()
        return {'username':data['u'],'role':row['role']}
    except Exception: raise HTTPException(401,'Invalid or expired session')

def admin(u=Depends(current_user)):
    if u['role']!='admin': raise HTTPException(403,'Admin permission required')
    return u

def op_or_admin(u=Depends(current_user)):
    if u['role'] not in ('admin','operator'): raise HTTPException(403,'Operator permission required')
    return u

class Login(BaseModel): username:str; password:str
class ServerIn(BaseModel): name:str=Field(min_length=2,max_length=70); region:str=Field(min_length=2,max_length=70); capacity:int=Field(default=100,ge=1,le=100000); monitor_url:str=''
class UserIn(BaseModel): username:str=Field(min_length=3,max_length=40); password:str=Field(min_length=8,max_length=100); role:str='viewer'
class StatusIn(BaseModel): status:str

async def background_monitor():
    # Checks run server-side while this Render service remains awake.
    while True:
        try:
            with db() as c:
                nodes=[dict(x) for x in c.execute("SELECT * FROM servers WHERE monitor_url IS NOT NULL AND monitor_url != ''")]
            for node in nodes:
                ping, detail, status = await asyncio.to_thread(check_target, node['monitor_url'])
                now=int(time.time())
                with db() as c:
                    c.execute('UPDATE servers SET status=?,last_ping_ms=?,last_checked=? WHERE id=?',(status,ping,now,node['id']))
                    c.execute('INSERT INTO history(server_id,status,ping_ms,created_at) VALUES(?,?,?,?)',(node['id'],status,ping,now))
                    if node['status'] != status:
                        level='critical' if status=='offline' else 'info'
                        name=node['name']; previous=node['status']
                        c.execute('INSERT INTO notices(title,message,level,created_at) VALUES(?,?,?,?)',('Server state changed',f'{name}: {previous} → {status}',level,now))
                        c.execute('INSERT INTO logs(level,message,created_at) VALUES(?,?,?)',(level.upper(),f'Background monitor {name}: {status}',now))
        except Exception as exc:
            log_event('WARNING',f'Background monitor error: {str(exc)[:120]}')
        await asyncio.sleep(60)

_monitor_task=None
@app.on_event('startup')
async def start_monitor():
    global _monitor_task
    _monitor_task=asyncio.create_task(background_monitor())
@app.on_event('shutdown')
async def stop_monitor():
    if _monitor_task:
        _monitor_task.cancel()


@app.get('/',response_class=HTMLResponse)
def home(): return (STATIC/'index.html').read_text(encoding='utf-8')
@app.get('/api/health')
def health(): return {'ok':True,'service':'MIDO SERVER ENGINE','version':'3.0','time':int(time.time())}
@app.post('/api/login')
def login(payload:Login):
    with db() as c: row=c.execute('SELECT * FROM users WHERE username=?',(payload.username,)).fetchone()
    if not row or not row['enabled'] or not password_verify(row['password_hash'],payload.password):
        log_event('WARNING',f'Failed login attempt for {payload.username}')
        with db() as c: c.execute('INSERT INTO notices(title,message,level,created_at) VALUES(?,?,?,?)',('Security alert',f'Failed login attempt: {payload.username}','warning',int(time.time())))
        raise HTTPException(401,'Invalid username or password')
    log_event('INFO',f'User {payload.username} logged in')
    return {'token':token_for(dict(row)),'user':{'username':row['username'],'role':row['role']}}
@app.get('/api/me')
def me(u=Depends(current_user)): return u
@app.get('/api/servers')
def servers(u=Depends(current_user)):
    with db() as c: items=[dict(x) for x in c.execute('SELECT * FROM servers ORDER BY name')]
    return {'servers':items,'count':len(items)}
@app.post('/api/servers')
def add_server(p:ServerIn,u=Depends(op_or_admin)):
    sid=uuid.uuid4().hex[:10]; now=int(time.time())
    with db() as c: c.execute('INSERT INTO servers(id,name,region,status,capacity,monitor_url,last_ping_ms,last_checked,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(sid,p.name,p.region,'unknown',p.capacity,p.monitor_url,None,None,now))
    log_event('INFO',f'{u["username"]} created server {p.name}'); return {'id':sid,'name':p.name,'region':p.region,'status':'unknown','capacity':p.capacity,'monitor_url':p.monitor_url}
@app.patch('/api/servers/{sid}')
def update_server(sid:str,p:StatusIn,u=Depends(op_or_admin)):
    if p.status not in ('online','offline','maintenance','unknown'): raise HTTPException(400,'Invalid status')
    with db() as c:
        r=c.execute('SELECT name FROM servers WHERE id=?',(sid,)).fetchone()
        if not r: raise HTTPException(404,'Server not found')
        c.execute('UPDATE servers SET status=? WHERE id=?',(p.status,sid))
    log_event('INFO',f'{u["username"]} changed {r["name"]} status to {p.status}'); return {'ok':True}
@app.delete('/api/servers/{sid}')
def delete_server(sid:str,u=Depends(admin)):
    with db() as c: cur=c.execute('DELETE FROM servers WHERE id=?',(sid,))
    if not cur.rowcount: raise HTTPException(404,'Server not found')
    log_event('WARNING',f'{u["username"]} deleted server {sid}'); return {'deleted':sid}

def check_target(url):
    if not url: return None,None,'unknown'
    try:
        parsed=urllib.parse.urlparse(url)
        if parsed.scheme not in ('https','http') or not parsed.hostname: return None,'Invalid URL','offline'
        ips={ipaddress.ip_address(x[4][0]) for x in socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80),type=socket.SOCK_STREAM)}
        if any(not ip.is_global for ip in ips): return None,'Private/non-public target blocked','offline'
    except Exception as e: return None,str(e)[:100],'offline'
    start=time.perf_counter()
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl): return None
    opener=urllib.request.build_opener(NoRedirect)
    try:
        req=urllib.request.Request(url,method='GET',headers={'User-Agent':'MidoServerMonitor/1.0'})
        with opener.open(req,timeout=6) as r: status=r.status
        return round((time.perf_counter()-start)*1000,1),status,'online' if status<500 else 'offline'
    except urllib.error.HTTPError as e:
        # HTTP response codes below 500 indicate that the endpoint responded.
        return round((time.perf_counter()-start)*1000,1),e.code,'online' if e.code<500 else 'offline'
    except Exception as e: return None,str(e)[:100],'offline'
@app.post('/api/servers/{sid}/check')
def check_one(sid:str,u=Depends(op_or_admin)):
    with db() as c: s=c.execute('SELECT * FROM servers WHERE id=?',(sid,)).fetchone()
    if not s: raise HTTPException(404,'Server not found')
    ping,detail,status=check_target(s['monitor_url'])
    if not s['monitor_url']: return {'checked':False,'message':'Set a monitor URL for real monitoring.','status':s['status']}
    now=int(time.time()); old=s['status']
    with db() as c:
        c.execute('UPDATE servers SET status=?,last_ping_ms=?,last_checked=? WHERE id=?',(status,ping,now,sid))
        c.execute('INSERT INTO history(server_id,status,ping_ms,created_at) VALUES(?,?,?,?)',(sid,status,ping,now))
        if old!=status:
            c.execute('INSERT INTO notices(title,message,level,created_at) VALUES(?,?,?,?)',('Server state changed',f'{s["name"]}: {old} → {status}','critical' if status=='offline' else 'info',now))
    log_event('INFO',f'Monitor check {s["name"]}: {status}, ping {ping}')
    return {'checked':True,'status':status,'ping_ms':ping,'detail':detail}
@app.post('/api/monitor/check-all')
def check_all(u=Depends(op_or_admin)):
    with db() as c: ss=[dict(x) for x in c.execute('SELECT * FROM servers')]
    results=[]
    for s in ss:
        if not s['monitor_url']: results.append({'id':s['id'],'checked':False,'status':s['status']}); continue
        ping,detail,status=check_target(s['monitor_url']); now=int(time.time())
        with db() as c:
            c.execute('UPDATE servers SET status=?,last_ping_ms=?,last_checked=? WHERE id=?',(status,ping,now,s['id']))
            c.execute('INSERT INTO history(server_id,status,ping_ms,created_at) VALUES(?,?,?,?)',(s['id'],status,ping,now))
            if s['status']!=status: c.execute('INSERT INTO notices(title,message,level,created_at) VALUES(?,?,?,?)',('Server state changed',f'{s["name"]}: {s["status"]} → {status}','critical' if status=='offline' else 'info',now))
        results.append({'id':s['id'],'checked':True,'status':status,'ping_ms':ping})
    log_event('INFO',f'{u["username"]} ran monitoring sweep'); return {'results':results}
@app.get('/api/history')
def history(sid:str|None=None,limit:int=150,u=Depends(current_user)):
    limit=max(1,min(limit,1000))
    with db() as c:
        q='SELECT * FROM history'; args=[]
        if sid: q+=' WHERE server_id=?'; args.append(sid)
        q+=' ORDER BY created_at DESC LIMIT ?'; args.append(limit)
        return {'history':[dict(x) for x in c.execute(q,args)]}
@app.get('/api/metrics')
def metrics(u=Depends(current_user)):
    with db() as c:
        rows=[dict(x) for x in c.execute('SELECT status,count(*) n FROM servers GROUP BY status')]
        count=c.execute('SELECT count(*) FROM servers').fetchone()[0]
        hist=[dict(x) for x in c.execute('SELECT ping_ms,created_at FROM history WHERE ping_ms IS NOT NULL ORDER BY created_at DESC LIMIT 80')]
    try:
        import psutil
        cpu=psutil.cpu_percent(interval=.15); ram=psutil.virtual_memory().percent; disk=psutil.disk_usage(str(ROOT)).percent
    except Exception: cpu=ram=disk=None
    return {'total':count,'counts':{x['status']:x['n'] for x in rows},'cpu_percent':cpu,'ram_percent':ram,'disk_percent':disk,'ping_history':list(reversed(hist)),'timestamp':int(time.time())}
@app.get('/api/logs')
def logs(limit:int=100,u=Depends(current_user)):
    with db() as c: return {'logs':[dict(x) for x in c.execute('SELECT * FROM logs ORDER BY id DESC LIMIT ?', (max(1,min(limit,500)),))]}
@app.get('/api/notices')
def notices(u=Depends(current_user)):
    with db() as c: return {'notices':[dict(x) for x in c.execute('SELECT * FROM notices ORDER BY id DESC LIMIT 100')]}
@app.post('/api/notices/{nid}/read')
def read_notice(nid:int,u=Depends(current_user)):
    with db() as c: c.execute('UPDATE notices SET read_flag=1 WHERE id=?',(nid,))
    return {'ok':True}
@app.get('/api/users')
def users(u=Depends(admin)):
    with db() as c: return {'users':[dict(x) for x in c.execute('SELECT id,username,role,created_at,enabled FROM users ORDER BY created_at DESC')]}
@app.post('/api/users')
def add_user(p:UserIn,u=Depends(admin)):
    if p.role not in ('admin','operator','viewer'): raise HTTPException(400,'Role must be admin, operator or viewer')
    try:
        with db() as c: c.execute('INSERT INTO users VALUES(?,?,?,?,?,1)',(uuid.uuid4().hex,p.username,password_hash(p.password),p.role,int(time.time())))
    except sqlite3.IntegrityError: raise HTTPException(409,'Username already exists')
    log_event('INFO',f'{u["username"]} created account {p.username}'); return {'ok':True}
@app.patch('/api/users/{uid}')
def edit_user(uid:str,payload:dict,u=Depends(admin)):
    role=payload.get('role'); enabled=payload.get('enabled')
    if role is not None and role not in ('admin','operator','viewer'): raise HTTPException(400,'Invalid role')
    with db() as c:
        row=c.execute('SELECT username FROM users WHERE id=?',(uid,)).fetchone()
        if not row: raise HTTPException(404,'User not found')
        if role is not None: c.execute('UPDATE users SET role=? WHERE id=?',(role,uid))
        if enabled is not None: c.execute('UPDATE users SET enabled=? WHERE id=?',(int(bool(enabled)),uid))
    log_event('WARNING',f'{u["username"]} modified account {row["username"]}'); return {'ok':True}
@app.delete('/api/users/{uid}')
def delete_user(uid:str,u=Depends(admin)):
    with db() as c:
        row=c.execute('SELECT username,role FROM users WHERE id=?',(uid,)).fetchone()
        if not row: raise HTTPException(404,'User not found')
        if row['username']==u['username']: raise HTTPException(400,'Cannot delete own account')
        c.execute('DELETE FROM users WHERE id=?',(uid,))
    log_event('WARNING',f'{u["username"]} removed account {row["username"]}'); return {'ok':True}
@app.get('/api/plugins')
def plugins(u=Depends(current_user)):
    with db() as c: return {'plugins':[dict(x) for x in c.execute('SELECT * FROM plugins ORDER BY name')]}
@app.patch('/api/plugins/{pid}')
def toggle_plugin(pid:str,payload:dict,u=Depends(admin)):
    with db() as c:
        r=c.execute('SELECT name FROM plugins WHERE id=?',(pid,)).fetchone()
        if not r: raise HTTPException(404,'Plugin not found')
        c.execute('UPDATE plugins SET enabled=? WHERE id=?',(int(bool(payload.get('enabled'))),pid))
    log_event('INFO',f'{u["username"]} toggled plugin {pid}'); return {'ok':True}
@app.get('/api/backup')
def backup(u=Depends(admin)):
    with db() as c:
        data={t:[dict(r) for r in c.execute(f'SELECT * FROM {t}')] for t in ('servers','users','logs','history','plugins','notices','match_rooms','tournaments','tournament_entries','profiles','store_items','store_orders')}
    return {'format':'mido-backup-v1','created_at':int(time.time()),'data':data}
@app.post('/api/restore')
def restore(payload:dict,u=Depends(admin)):
    if payload.get('format')!='mido-backup-v1' or not isinstance(payload.get('data'),dict): raise HTTPException(400,'Invalid backup format')
    tables=('servers','users','logs','history','plugins','notices','match_rooms','tournaments','tournament_entries','profiles','store_items','store_orders')
    try:
        with db() as c:
            for t in tables:
                if t in payload['data']:
                    c.execute(f'DELETE FROM {t}')
                    rows=payload['data'][t]
                    if rows:
                        cols=list(rows[0].keys()); sql=f'INSERT INTO {t} ({",".join(cols)}) VALUES ({",".join("?" for _ in cols)})'
                        c.executemany(sql,[tuple(row.get(k) for k in cols) for row in rows])
    except Exception as e: raise HTTPException(400,f'Restore failed: {str(e)[:150]}')
    log_event('WARNING',f'{u["username"]} restored a backup'); return {'ok':True}


# ---- MIDO ARENA add-on endpoints (persistent demo/community features) ----
def ensure_profile(username):
    with db() as c:
        c.execute('INSERT OR IGNORE INTO profiles(username,coins,display_name,created_at) VALUES(?,?,?,?)',(username,500,username,int(time.time())))
        row=c.execute('SELECT * FROM profiles WHERE username=?',(username,)).fetchone()
        return dict(row)

@app.get('/api/arena/overview')
def arena_overview(u=Depends(current_user)):
    profile=ensure_profile(u['username'])
    with db() as c:
        rooms=[dict(r) for r in c.execute("SELECT * FROM match_rooms WHERE status='waiting' ORDER BY created_at DESC LIMIT 20")]
        counts=c.execute("SELECT status,count(*) n FROM servers GROUP BY status").fetchall()
        regions=[dict(r) for r in c.execute('SELECT region,status,count(*) n,AVG(last_ping_ms) avg_ping FROM servers GROUP BY region,status')]
    return {'profile':profile,'rooms':rooms,'server_regions':regions,'server_counts':{r['status']:r['n'] for r in counts}}

@app.get('/api/arena/rooms')
def arena_rooms(u=Depends(current_user)):
    with db() as c: return {'rooms':[dict(r) for r in c.execute("SELECT * FROM match_rooms WHERE status='waiting' ORDER BY created_at DESC LIMIT 50")]}

@app.post('/api/arena/quickmatch')
def arena_quickmatch(payload:dict,u=Depends(current_user)):
    with db() as c:
        node=c.execute("SELECT * FROM servers WHERE status='online' ORDER BY COALESCE(last_ping_ms,999999) ASC LIMIT 1").fetchone()
    region=node['region'] if node else 'Global lobby'
    sid=node['id'] if node else None
    rid=uuid.uuid4().hex[:8].upper(); code=secrets.token_hex(3).upper()
    with db() as c:
        c.execute('INSERT INTO match_rooms VALUES(?,?,?,?,?,?,?,?,?)',(rid,'Quick Match Lobby','Quick Match',region,sid,u['username'],code,'waiting',int(time.time())))
    log_event('INFO',f'{u["username"]} opened quick match lobby {rid}')
    return {'room':{'id':rid,'title':'Quick Match Lobby','mode':'Quick Match','region':region,'server_id':sid,'creator':u['username'],'code':code,'status':'waiting'},'note':'Lobby created. Actual game matchmaking/gameplay requires a game client and game server integration.'}

@app.post('/api/arena/rooms')
def arena_create_room(payload:dict,u=Depends(current_user)):
    title=str(payload.get('title','Private Match')).strip()[:48] or 'Private Match'
    region=str(payload.get('region','Global')).strip()[:48] or 'Global'
    mode=str(payload.get('mode','Friendly')).strip()[:30] or 'Friendly'
    code=secrets.token_hex(3).upper(); rid=uuid.uuid4().hex[:8].upper()
    with db() as c: c.execute('INSERT INTO match_rooms VALUES(?,?,?,?,?,?,?,?,?)',(rid,title,mode,region,None,u['username'],code,'waiting',int(time.time())))
    log_event('INFO',f'{u["username"]} created match room {rid}')
    return {'room':{'id':rid,'title':title,'mode':mode,'region':region,'creator':u['username'],'code':code,'status':'waiting'}}

@app.post('/api/arena/rooms/{room_id}/join')
def arena_join_room(room_id:str,u=Depends(current_user)):
    with db() as c: room=c.execute("SELECT * FROM match_rooms WHERE id=? AND status='waiting'",(room_id,)).fetchone()
    if not room: raise HTTPException(404,'Room not found or no longer available')
    log_event('INFO',f'{u["username"]} requested to join room {room_id}')
    return {'ok':True,'room':dict(room),'message':'Join request recorded in activity log. Game client integration is required for live player sessions.'}

@app.get('/api/arena/tournaments')
def arena_tournaments(u=Depends(current_user)):
    with db() as c:
        ts=[dict(r) for r in c.execute('SELECT * FROM tournaments ORDER BY starts_at')]
        for t in ts: t['players']=c.execute('SELECT COUNT(*) FROM tournament_entries WHERE tournament_id=?',(t['id'],)).fetchone()[0]
    return {'tournaments':ts}

@app.post('/api/arena/tournaments/{tid}/join')
def arena_join_tournament(tid:str,u=Depends(current_user)):
    with db() as c:
        t=c.execute('SELECT * FROM tournaments WHERE id=? AND status=?',(tid,'open')).fetchone()
        if not t: raise HTTPException(404,'Tournament is not open')
        try: c.execute('INSERT INTO tournament_entries(tournament_id,username,created_at) VALUES(?,?,?)',(tid,u['username'],int(time.time())))
        except sqlite3.IntegrityError: return {'ok':True,'already_joined':True}
    log_event('INFO',f'{u["username"]} joined tournament {tid}')
    return {'ok':True,'joined':True}

@app.get('/api/arena/store')
def arena_store(u=Depends(current_user)):
    profile=ensure_profile(u['username'])
    with db() as c:
        items=[dict(r) for r in c.execute('SELECT * FROM store_items WHERE active=1 ORDER BY category,title')]
        orders=[dict(r) for r in c.execute('SELECT * FROM store_orders WHERE username=? ORDER BY created_at DESC LIMIT 20',(u['username'],))]
    return {'items':items,'coins':profile['coins'],'orders':orders}

@app.post('/api/arena/store/{item_id}/buy')
def arena_buy(item_id:str,u=Depends(current_user)):
    ensure_profile(u['username'])
    with db() as c:
        item=c.execute('SELECT * FROM store_items WHERE id=? AND active=1',(item_id,)).fetchone()
        if not item: raise HTTPException(404,'Item unavailable')
        prof=c.execute('SELECT coins FROM profiles WHERE username=?',(u['username'],)).fetchone()
        if prof['coins']<item['price_coins']: raise HTTPException(400,'Not enough demo coins')
        c.execute('UPDATE profiles SET coins=coins-? WHERE username=?',(item['price_coins'],u['username']))
        oid=uuid.uuid4().hex[:12]
        c.execute('INSERT INTO store_orders VALUES(?,?,?,?,?,?)',(oid,u['username'],item_id,item['title'],item['price_coins'],int(time.time())))
    log_event('INFO',f'{u["username"]} demo-purchased {item["title"]}')
    return {'ok':True,'coins_remaining':prof['coins']-item['price_coins'],'order_id':oid,'note':'Demo coin purchase only; no real payment was processed.'}

@app.get('/api/arena/profile')
def arena_profile(u=Depends(current_user)):
    profile=ensure_profile(u['username'])
    with db() as c: orders=[dict(r) for r in c.execute('SELECT * FROM store_orders WHERE username=? ORDER BY created_at DESC LIMIT 30',(u['username'],))]
    return {'profile':profile,'orders':orders,'user':u}
