# Cold-chain AI agent

This project monitors simulated refrigerated trucks, stores trip-scoped telemetry in MySQL, evaluates configured safety rules deterministically, and uses LangGraph for live investigation and explicitly requested completed-trip reports.

## Architecture

`backend/truck_simulator.py` creates an ACTIVE trip and emits telemetry every `SIMULATION_INTERVAL_SECONDS`. Repositories in `database/` own MySQL access. `retrieval/`, `eta_service.py`, `weather/`, and `risk_engine.py` provide authoritative evidence and deterministic calculations. `agent/` orchestrates tool calls and structured Pydantic outputs. `api/main.py` is a thin FastAPI interface.

Normal monitoring ends with `CONTINUE_MONITORING`; risky monitoring can retrieve the relevant SOP and produce an `ActionOutput`. Completing a trip only marks `trips.status=COMPLETED`; it never generates a report. Reports are generated only by an explicit agent request or `GET /trips/{trip_id}/report`.

## Setup

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m database.init_db
```

Set `DB_*` and `OPENAI_API_KEY` in `.env` before using MySQL or LLM workflows. No credentials belong in source control.

Create routes with the existing `Route` and `database.route_repository.save_route` functions, then start the simulator:

```powershell
python -m backend.truck_simulator
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Start the dashboard in a second terminal:

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

The frontend uses one API client and these backend contracts: `GET /trucks/active`, `GET /simulation`, `POST /simulation/start`, `POST /simulation/stop`, `GET /trips`, `GET /trips/{trip_id}/telemetry`, `GET /routes/{route_id}`, `GET /trucks/{truck_id}/weather`, `POST /agent/query`, and `GET /trips/{trip_id}/report`.

Index SOP files by calling `sop_rag.index_sop(path)` from a Python shell. Use `POST /agent/query` for live questions and `GET /trips/TRIP_001/report` for an on-demand report.

## Database

Initialization is idempotent and creates `routes`, `route_waypoints`, `trips`, and `telemetry`. Telemetry is linked by `telemetry.trip_id`; trip lifecycle fields include status, start/completion timestamps, and audit timestamps. Existing tables receive the missing `trip_id` column during initialization.

## Workflow

Simulator → ACTIVE trip → telemetry with `trip_id` → active retrieval → ETA → weather at next station/ETA → deterministic risk → LangGraph investigation → relevant SOP → `ActionOutput`.

Explicit report request → trip-scoped historical retrieval → deterministic temperature/operations analysis → structured `TripReport`.

## Troubleshooting

If MySQL is unavailable, initialize/start MySQL and verify `.env`. If weather is unavailable, the agent should preserve a structured service error rather than inventing weather. A report requires historical telemetry and will retain missing values as unavailable. Run `python -m compileall agent backend database retrieval weather` to check syntax/import compilation.
"# COLD_CHAIN" 
