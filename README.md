# MIDO SERVER ENGINE v0.1

A starter control panel and API for managing **server node records**. This is a prototype: the nodes are configuration entries, not actual game servers. Live matchmaking, game sessions, player telemetry, and ping measurement are not implemented yet.


## Run locally

```bash
python -m pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```
Open `http://127.0.0.1:8000`.

## API
- `GET /api/health` health check
- `GET /api/servers` list nodes
- `POST /api/servers` create node (JSON: `name`, `region`, `capacity`)
- `PATCH /api/servers/{id}` change status to `online`, `offline`, or `maintenance`
- `DELETE /api/servers/{id}` remove node


## Deploy to Render
Create a new Web Service from this repository. Render reads `render.yaml`; alternatively set build command `pip install -r requirements.txt`, start command `uvicorn app:app --host 0.0.0.0 --port $PORT`, and health path `/api/health`. The free instance may spin down and the JSON file may not be durable across restarts/redeploys; use a persistent database before production.
