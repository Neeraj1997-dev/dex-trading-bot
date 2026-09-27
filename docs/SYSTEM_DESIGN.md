# DEX Trading Platform — System Design

Automated trading console for [Delta Exchange](https://docs.delta.exchange/#introduction). The model may suggest a trade. Deterministic risk rules decide whether an order is allowed.

![System design](png/system-design.png)

## 1. Purpose

| Goal | How it is met |
| --- | --- |
| Live market data | Delta public tickers (`BTCUSD`, `ETHUSD`) |
| Structured analysis | OpenAI JSON when configured; heuristic baseline when it is not |
| Safe execution | Risk engine, kill switch, circuit breaker, duplicate-signal block |
| Operator control | React dashboard: start, stop, pause, mode, risk limits, approvals |
| Audit | Every control and order is written to `audit_logs` |
| Default safety | Paper fills at live prices. Live orders stay off until explicitly enabled |

## 2. Containers

```text
Operator browser
    → React dashboard          :3000
    → FastAPI                  :8080   /api/v1
    → MongoDB 7                :27017  database dex_trading
    → Delta Exchange API       https://api.india.delta.exchange
```

Docker Compose runs `mongo`, `api`, and `web`. The API waits until MongoDB is healthy. The dashboard is a static Nginx build that calls the API in the browser.

Secrets (`JWT_SECRET`, `DELTA_API_SECRET`, `OPENAI_API_KEY`, WhatsApp keys) are environment variables on the API process. They are never sent to the browser or to OpenAI.

## 3. Trading cycle

The scheduler polls markets every 15 seconds and runs an engine cycle every 30 seconds. A cycle does this, in order:

1. **Market data.** Load enabled pairs, fetch Delta tickers, store a snapshot. Quotes older than `MARKET_STALE_SECONDS` are marked stale and cannot open a trade.
2. **AI analysis.** Build a validated `AiAnalysis` object: decision, entry, take-profit, stop-loss, confidence, risk level, and a short reason. Invalid model output becomes `NO_TRADE`.
3. **Risk engine.** Reject the signal if any rule fails. AI text cannot skip this step.
4. **Mode gate.**
   - `PAPER` and `AUTO` may execute after risk approval.
   - `MANUAL_APPROVAL` stores the signal until the operator approves it. Approval runs the risk check again.
5. **Executor.** Submit the order, store request, response, and transaction hash. The same signal cannot be filled twice.
6. **Positions.** Mark open positions to the latest price. Close them when take-profit or stop-loss is hit.

`NO_TRADE` is still stored once per time window so the dashboard shows why nothing was done.

## 4. Modes

| Mode | Prices | Orders |
| --- | --- | --- |
| `PAPER` | Live Delta | Simulated fill (`delta_sim_…`) |
| `MANUAL_APPROVAL` | Live Delta | Only after the operator approves, and only if risk still passes |
| `AUTO` | Live Delta | Automatic after risk checks |

`AUTO` does not place a real Delta order unless `DELTA_LIVE_TRADING=true` and both `DELTA_API_KEY` and `DELTA_API_SECRET` are set. Otherwise the executor still simulates the fill at the live mark price.

## 5. Risk rules

A buy is allowed only when all of these hold:

- Kill switch is off and the circuit breaker is closed
- Decision is not `NO_TRADE`
- Quote is not stale
- Confidence is at least `min_confidence`
- Liquidity is at least `min_liquidity_usd`
- Estimated fee is within `max_gas_usd`
- Price is close enough to the suggested entry (`max_slippage_bps`)
- Daily loss, trade count, open positions, balance, and portfolio exposure are inside limits
- The symbol does not already have an open position

Take-profit and stop-loss used on the position come from the configured percentages, not from unvalidated model text.

The circuit breaker opens on an 8% single-tick move, five failures in five minutes, or a daily loss at the configured cap.

## 6. Data model

Database: MongoDB `dex_trading`. Documents are Beanie models.

| Collection | Role |
| --- | --- |
| `users` | Dashboard login (bcrypt password, JWT subject) |
| `bot_state` | Status, mode, kill switch, risk limits, pairs, circuit breaker |
| `market_snapshots` | Price, 24h change, volume, liquidity, timestamp, source |
| `signals` | Analysis, fingerprint, status, risk rejections |
| `orders` | Side, size, fill, fees, tx hash, raw request and response |
| `positions` | Entry, mark, unrealized and realized P&L, TP, SL, fees |
| `portfolio` | Cash, invested amount, daily and realized P&L, win/loss counts |
| `audit_logs` | Actor, action, entity, redacted details |
| `trade_history` | Closed trades and exit reason (`TAKE_PROFIT`, `STOP_LOSS`) |

Signal fingerprints stop the same idea from executing again inside a 15-minute window.

## 7. API

Base path: `/api/v1`. Interactive schema: `http://localhost:8080/docs`.

| Area | Endpoints |
| --- | --- |
| Auth | `POST /auth/login` |
| Health | `GET /health` |
| Dashboard | `GET /dashboard` |
| Bot | `POST /bot/control`, `PUT /bot/mode`, `PUT /bot/risk`, `PUT /bot/pairs`, `POST /bot/cycle` |
| Trading | `GET /positions`, `GET /orders`, `GET /signals`, `GET /markets` |
| Approval | `POST /signals/{id}/approve` |
| Audit | `GET /audit` |
| WhatsApp | `GET /notifications/whatsapp`, `POST /notifications/whatsapp/test` |

Everything except login and health requires an admin JWT.

Bot actions: `START`, `STOP`, `PAUSE`, `RESUME`, `KILL_SWITCH`, `RESET_KILL_SWITCH`.

## 8. Dashboard

The React app is a single console:

- **Overview** — portfolio value, balance, P&L, win rate, bot controls
- **Positions, orders, signals, markets, history**
- **Settings** — risk limits, pair toggles, connection status, optional WhatsApp test

On narrow screens the sidebar becomes a drawer and primary sections move to a bottom navigation bar.

## 9. External systems

| System | Required | Use |
| --- | --- | --- |
| Delta Exchange | Yes for live quotes | `GET /v2/tickers/{symbol}`. Private `POST /v2/orders` only when live trading is on. HMAC signature: `method + timestamp + path + query + body`. |
| OpenAI | No | JSON analysis only. Missing key uses the heuristic baseline. |
| WhatsApp | No | Off unless `WHATSAPP_ENABLED=true` and a provider key is set. |

## 10. Security

- JWT access tokens, bcrypt passwords, admin role on mutating routes
- Production refuses the default JWT secret and the default admin password
- Audit details redact fields whose names contain key, secret, password, private, or mnemonic
- Wallet and exchange secrets never leave the API process
- Kill switch blocks new entries immediately and does not require a model response

## 11. Failure handling

| Failure | Behavior |
| --- | --- |
| Delta timeout or HTTP error | Snapshot skipped, failure counted toward the circuit breaker |
| Stale or unparsable quote time | Treated as not tradable |
| OpenAI timeout or invalid JSON | `NO_TRADE` |
| Order rejected or slippage too wide | Order stored as `FAILED`, position stays unchanged |
| Exit order fails | Position returns to `OPEN` |
| Process restart | Bot state, positions, and orders are read back from MongoDB |

## 12. Repository

```text
backend/app
  api/routes          HTTP API
  core                settings, enums, logging
  db                  MongoDB connect and seed
  models              Beanie documents and Pydantic schemas
  services
    market            ticker ingest
    ai                structured analysis
    risk              deterministic checks
    executor          order submit and record
    position          mark-to-market and exits
    dex               Delta, paper, and 1inch adapters
    engine            cycle orchestrator
    circuit           volatility and failure breaker
    audit             audit log
    auth              passwords and JWT
    notify            optional WhatsApp
  workers             APScheduler
frontend              React dashboard
docs/png              system-design.png
docker-compose.yml
```

## 13. Runtime defaults

| Setting | Default |
| --- | --- |
| Provider | `delta` |
| Mode | `PAPER` |
| Pairs | `BTCUSD`, `ETHUSD` |
| Paper balance | 100,000 USD |
| Max position | 1,000 USD |
| Max daily loss | 500 USD |
| Stop-loss / take-profit | 3% / 6% |
| Min confidence | 60 |
| Live Delta orders | off |
| WhatsApp | off |
