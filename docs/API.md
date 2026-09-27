# API Reference

Base URL: `http://localhost:8080/api/v1`

Interactive docs: `http://localhost:8080/docs`

Authentication: `Authorization: Bearer <jwt>`

## Auth

### `POST /auth/login`

```json
{ "email": "admin@localhost", "password": "ChangeMeNow!123" }
```

Response:

```json
{ "access_token": "<jwt>", "token_type": "bearer" }
```

## System

### `GET /health`

Public health check for MongoDB, DEX, and OpenAI connectivity.

### `GET /dashboard`

Full dashboard snapshot: bot state, portfolio, positions, orders, signals, connections, markets, trade history.

### `GET /audit`

Recent audit log entries (secrets redacted).

## Bot controls

### `POST /bot/control`

```json
{ "action": "START|STOP|PAUSE|RESUME|KILL_SWITCH|RESET_KILL_SWITCH" }
```

### `PUT /bot/mode`

```json
{ "mode": "PAPER|MANUAL_APPROVAL|AUTO" }
```

### `PUT /bot/risk`

```json
{
  "limits": {
    "max_position_size_usd": 1000,
    "max_daily_loss_usd": 500,
    "max_trades_per_day": 20,
    "max_portfolio_exposure_pct": 50,
    "stop_loss_pct": 3,
    "take_profit_pct": 6,
    "max_slippage_bps": 100,
    "min_liquidity_usd": 50000,
    "max_gas_usd": 25,
    "min_confidence": 60,
    "max_open_positions": 5
  }
}
```

### `PUT /bot/pairs`

```json
{ "symbol": "ETH/USDC", "enabled": true }
```

### `POST /bot/cycle`

Manually trigger one engine cycle.

## Trading data

- `GET /positions`
- `GET /orders`
- `GET /signals`
- `GET /markets`
- `POST /signals/{id}/approve` with `{ "approve": true|false }`

## Architecture pipeline

```
Market Data → AI Analysis (structured JSON) → Risk Engine → Trade Executor → Position Manager
```

AI output is validated with Pydantic before risk evaluation. Risk rules are deterministic and cannot be bypassed by model text.
