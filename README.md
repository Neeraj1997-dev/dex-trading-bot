# Automated DEX Trading Platform

Production-oriented **Python + MongoDB** trading platform with OpenAI structured market analysis, deterministic risk controls, paper/manual/auto modes, and a React monitoring dashboard.

> Start in **PAPER** mode. AI never bypasses risk. Private keys and API secrets stay server-side only.

## Architecture

```
Market Data → Strategy / AI Analysis → Risk Engine → Trade Executor → Position Manager → Monitoring
```

| Layer | Responsibility |
|---|---|
| **Market** | Fetch prices/liquidity/volume from DEX (paper/mock/1inch) and store history in MongoDB |
| **AI** | OpenAI structured JSON analysis (`BUY` / `SELL` / `NO_TRADE`) with Pydantic validation |
| **Risk** | Deterministic limits: size, daily loss, trades, exposure, SL/TP, slippage, liquidity, gas, confidence |
| **Executor** | Submit orders, record request/response/tx hash; duplicate-signal protection |
| **Positions** | Track entry/current/PnL/fees; auto-close on take-profit or stop-loss |
| **Circuit breaker** | Trips on volatility spikes, repeated failures, or excessive daily loss |
| **Kill switch** | Immediately disables new trades |

## Stack

- **Backend:** Python 3.12, FastAPI, Beanie/Motor (async MongoDB)
- **Database:** MongoDB 7
- **Exchange:** [Delta Exchange API](https://docs.delta.exchange/#introduction) (`DEX_PROVIDER=delta`)
- **AI:** OpenAI Chat Completions with JSON object response + schema validation
- **Frontend:** React + Vite TypeScript dashboard
- **Ops:** Docker Compose, structured JSON logs, audit trail

## Quick start (Docker + Delta)

```bash
cp .env.example .env
# Optional: set DELTA_API_KEY / DELTA_API_SECRET for private endpoints
# Keep DELTA_LIVE_TRADING=false until you want real orders
docker compose up -d --build
```

- API / docs: http://localhost:8080/docs  
- Dashboard: http://localhost:3000  
- Login: `admin@localhost` / `ChangeMeNow!123`

By default the bot uses **live Delta public tickers** (`BTCUSD`, `ETHUSD`) with **PAPER** fills (simulated). Set `DELTA_LIVE_TRADING=true` plus API credentials only when ready for real orders.

## Local development

### Prerequisites

- Python 3.11+
- Node.js 20+
- MongoDB 7 (`docker run -d -p 27017:27017 mongo:7`)

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env
# set MONGODB_URI=mongodb://localhost:27017
uvicorn app.main:app --reload --port 8080
```

### Frontend

```bash
cd frontend
npm install
echo 'VITE_API_URL=http://localhost:8080/api/v1' > .env
npm run dev
```

### Tests

```bash
cd backend
pytest -q
```

## Trading modes

| Mode | Behavior |
|---|---|
| **PAPER** | Simulate fills via paper DEX (default, no real funds) |
| **MANUAL_APPROVAL** | AI+risk produce signals; user approves in dashboard |
| **AUTO** | Execute after risk checks (live DEX requires server-side wallet config) |

## WhatsApp notifications (optional)

WhatsApp alerts are **disabled by default**. To enable:

1. Create a free [CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/) API key (or use Twilio / Meta).
2. Set in `.env`:

```bash
WHATSAPP_ENABLED=true
WHATSAPP_TO=6206240867
WHATSAPP_PROVIDER=callmebot
CALLMEBOT_APIKEY=your_key_here
```

3. Restart API: `docker compose up -d --build api`
4. In the dashboard → **Settings → WhatsApp alerts → Send test**

When enabled, alerts cover bot start/stop/kill, signals, order fills/failures, position exits, and circuit breaker.

- AI responses must pass `AiAnalysis` schema validation before risk/execution
- Risk engine independently enforces all limits
- Signal fingerprints prevent duplicate execution in the same time bucket
- Stale market data, kill switch, and circuit breaker block new entries
- Audit logs redact secrets (`key`, `secret`, `password`, `private`, …)
- Wallet private keys are never sent to the frontend or OpenAI
- Live 1inch broadcast is gated in this template; use paper mode first

## Configuration

See [`.env.example`](.env.example). Important variables:

| Variable | Purpose |
|---|---|
| `MONGODB_URI` / `MONGODB_DB` | MongoDB connection |
| `JWT_SECRET` | Auth signing (≥32 chars) |
| `OPENAI_API_KEY` | Optional; heuristic fallback if unset |
| `DEX_PROVIDER` | `paper` \| `mock` \| `oneinch` |
| `TRADING_MODE` | `PAPER` \| `MANUAL_APPROVAL` \| `AUTO` |
| `WALLET_PRIVATE_KEY` | Server-only; required for live AUTO (not exposed) |

## API documentation

See [docs/API.md](docs/API.md) and OpenAPI at `/docs`.

## Repository layout

```
backend/app/
  api/routes/        # FastAPI routes
  core/              # config, enums, logging
  db/                # MongoDB bootstrap
  models/            # Beanie documents + Pydantic schemas
  services/
    market/ ai/ risk/ executor/ position/
    dex/ engine/ circuit/ audit/ auth/
  workers/           # APScheduler cycles
frontend/            # React dashboard
docs/                # API docs
docker-compose.yml
```

## Deployment notes

1. Change `JWT_SECRET` and `ADMIN_PASSWORD`
2. Keep `TRADING_MODE=PAPER` until paper results look sane
3. Store `OPENAI_API_KEY`, `DEX_API_KEY`, and `WALLET_PRIVATE_KEY` in a secrets manager
4. Put TLS termination in front of the API
5. Restrict MongoDB network access
6. Monitor audit logs and circuit-breaker events

## License

See [LICENSE](LICENSE).
