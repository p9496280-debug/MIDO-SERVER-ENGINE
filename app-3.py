from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import json, uuid, time, os

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
# Render persistent disk: set DATA_DIR to the disk mount path (e.g. /var/data)
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / "servers.json"
DEFAULTS = [
    {"id":"eg-cairo-01","name":"Egypt • Cairo","region":"Cairo, EG","status":"online","players":0,"capacity":100,"ping":24,"created_at":int(time.time())},
    {"id":"eu-frankfurt-01","name":"Europe • Frankfurt","region":"Frankfurt, DE","status":"maintenance","players":0,"capacity":100,"ping":92,"created_at":int(time.time())},
]

def load_nodes():
    if not DB.exists():
        save_nodes(DEFAULTS)
    try:
        data = json.loads(DB.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else DEFAULTS.copy()
    except (json.JSONDecodeError, OSError):
        return DEFAULTS.copy()

def save_nodes(nodes):
    DB.write_text(json.dumps(nodes, indent=2, ensure_ascii=False), encoding="utf-8")

app = FastAPI(title="MIDO SERVER ENGINE", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ServerIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    region: str = Field(min_length=2, max_length=60)
    capacity: int = Field(default=100, ge=1, le=100000)



@app.get("/", response_class=HTMLResponse)
def home():
    page = STATIC / "index.html"
    if not page.exists():
        raise HTTPException(500, "Frontend file missing")
    return page.read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    return {"ok": True, "service":"MIDO SERVER ENGINE", "version":"1.0.0", "timestamp":int(time.time())}

@app.get("/api/servers")
def get_servers():
    nodes = load_nodes()
    return {"servers": nodes, "count": len(nodes)}

@app.post("/api/servers")
def add_server(payload: ServerIn):
    nodes = load_nodes()
    node = {"id":uuid.uuid4().hex[:10], "name":payload.name.strip(), "region":payload.region.strip(), "status":"offline", "players":0, "capacity":payload.capacity, "ping":None, "created_at":int(time.time())}
    nodes.append(node); save_nodes(nodes)
    return node
@app.patch("/api/servers/{server_id}")
def update_server(server_id: str, payload: dict):
    nodes = load_nodes()
    for node in nodes:
        if node["id"] == server_id:
            status = payload.get("status")
            if status not in ("online", "offline", "maintenance"):
                raise HTTPException(400, "Invalid status")
            node["status"] = status; save_nodes(nodes); return node
    raise HTTPException(404, "Server not found")
@app.delete("/api/servers/{server_id}")
def delete_server(server_id: str):
    nodes = load_nodes(); new = [n for n in nodes if n["id"] != server_id]
    if len(new) == len(nodes): raise HTTPException(404, "Server not found")
    save_nodes(new); return {"deleted":server_id}
