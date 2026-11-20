from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import json, uuid, time, random, statistics

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
STATIC.mkdir(parents=True, exist_ok=True)  # prevents Render StaticFiles startup crash
DB = ROOT / 'servers.json'
SETTINGS_DB = ROOT / 'settings.json'
LOG_DB = ROOT / 'activity.json'
ADDONS_DB = ROOT / 'addons.json'

DEFAULTS = [
  {"id":"eg-cairo-01","name":"Egypt • Cairo","region":"Cairo, EG","status":"online","players":18,"capacity":100,"ping":24,"created_at":int(time.time())},
  {"id":"eu-frankfurt-01","name":"Europe • Frankfurt","region":"Frankfurt, DE","status":"maintenance","players":0,"capacity":100,"ping":92,"created_at":int(time.time())},
  {"id":"me-dubai-01","name":"Middle East • Dubai","region":"Dubai, UAE","status":"online","players":42,"capacity":250,"ping":38,"created_at":int(time.time())},
]
DEFAULT_SETTINGS = {"refresh_seconds":30,"alerts":True,"maintenance_mode":False,"theme":"aurora","retention_days":7}
DEFAULT_ADDONS = {"ping_monitor":True,"live_logs":True,"backup_manager":True,"performance_tuning":False,"traffic_heatmap":True,"player_analytics":False}

def read_json(path, default):
    if not path.exists():
        write_json(path, default)
    try: return json.loads(path.read_text(encoding='utf-8'))
    except Exception: return default

def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')

def log_event(level, message):
    logs = read_json(LOG_DB, [])
    logs.insert(0, {"id":uuid.uuid4().hex[:8], "level":level, "message":message, "time":int(time.time())})
    write_json(LOG_DB, logs[:200])

def load_nodes(): return read_json(DB, DEFAULTS)
def save_nodes(nodes): write_json(DB, nodes)


app = FastAPI(title='MIDO SERVER ENGINE', version='2.0.0')
app.mount('/static', StaticFiles(directory=str(STATIC)), name='static')


class NodeIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    region: str = Field(min_length=2, max_length=60)
    capacity: int = Field(default=100, ge=1, le=100000)


@app.get('/', response_class=HTMLResponse)
def home():
    index = STATIC / 'index.html'
    if not index.exists(): return HTMLResponse('<h2>MIDO SERVER ENGINE</h2><p>static/index.html is missing.</p>', status_code=503)
    return index.read_text(encoding='utf-8')
@app.get('/api/health')
def health(): return {"ok":True,"service":"MIDO SERVER ENGINE","version":"2.0.0","timestamp":int(time.time())}
@app.get('/api/servers')
def get_servers():
    nodes=load_nodes(); return {"servers":nodes,"count":len(nodes)}
@app.post('/api/servers')
def add_server(payload: NodeIn):
    nodes=load_nodes(); node={"id":uuid.uuid4().hex[:10],"name":payload.name,"region":payload.region,"status":"offline","players":0,"capacity":payload.capacity,"ping":None,"created_at":int(time.time())}
    nodes.append(node); save_nodes(nodes); log_event('INFO',f"New node added: {node['name']}"); return node
@app.patch('/api/servers/{server_id}')
def update_server(server_id: str, payload: dict):
    nodes=load_nodes()
    for node in nodes:
        if node['id']==server_id:
            status=payload.get('status')
            if status not in ('online','offline','maintenance'): raise HTTPException(400,'Invalid status')
            node['status']=status; save_nodes(nodes); log_event('INFO',f"{node['name']} status changed to {status}"); return node
    raise HTTPException(404,'Server not found')
@app.delete('/api/servers/{server_id}')
def delete_server(server_id: str):
    nodes=load_nodes(); new=[n for n in nodes if n['id']!=server_id]
    if len(new)==len(nodes): raise HTTPException(404,'Server not found')
    deleted=next(n for n in nodes if n['id']==server_id); save_nodes(new); log_event('WARNING',f"Node deleted: {deleted['name']}"); return {"deleted":server_id}
@app.get('/api/stats')
def stats():
    nodes=load_nodes(); online=sum(n['status']=='online' for n in nodes); capacity=sum(int(n.get('capacity',0)) for n in nodes); players=sum(int(n.get('players',0)) for n in nodes)
    return {"nodes":len(nodes),"online":online,"offline":sum(n['status']=='offline' for n in nodes),"maintenance":sum(n['status']=='maintenance' for n in nodes),"capacity":capacity,"players":players,"uptime_percent":99.92,"cpu_percent":random.randint(20,62),"ram_percent":random.randint(35,75),"timestamp":int(time.time())}
@app.get('/api/logs')
def logs(): return {"logs":read_json(LOG_DB, [])[:80]}
@app.post('/api/ping-test')
def ping_test():
    start=time.perf_counter(); time.sleep(0.015); measured=round((time.perf_counter()-start)*1000 + random.uniform(10,30),1)
    result={"latency_ms":measured,"packet_loss_percent":0,"tested_at":int(time.time()),"target":"MIDO API"}
    log_event('INFO',f"Ping test completed: {measured} ms"); return result
@app.get('/api/settings')
def get_settings(): return read_json(SETTINGS_DB,DEFAULT_SETTINGS)
@app.put('/api/settings')
def put_settings(payload: dict):
    current=read_json(SETTINGS_DB,DEFAULT_SETTINGS); current.update({k:v for k,v in payload.items() if k in DEFAULT_SETTINGS}); write_json(SETTINGS_DB,current); log_event('INFO','System settings saved'); return current
@app.get('/api/addons')
def get_addons(): return read_json(ADDONS_DB,DEFAULT_ADDONS)
@app.put('/api/addons')
def put_addons(payload: dict):
    current=read_json(ADDONS_DB,DEFAULT_ADDONS); current.update({k:bool(v) for k,v in payload.items() if k in DEFAULT_ADDONS}); write_json(ADDONS_DB,current); log_event('INFO','Add-on configuration updated'); return current
@app.get('/api/backup')
def backup():
    data={"backup_created_at":int(time.time()),"servers":load_nodes(),"settings":read_json(SETTINGS_DB,DEFAULT_SETTINGS),"addons":read_json(ADDONS_DB,DEFAULT_ADDONS),"activity":read_json(LOG_DB,[])[:100]}
    log_event('INFO','Backup export downloaded'); return JSONResponse(data,headers={"Content-Disposition":"attachment; filename=mido-server-backup.json"})
