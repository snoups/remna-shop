# 🛍 Remnatrishop

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/github/license/elcrazycol/remnatrishop)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-ghcr.io%2Felcrazycol%2Fremnatrishop-2496ED?logo=docker&logoColor=white)](https://github.com/elcrazycol/remnatrishop/pkgs/container/remnatrishop)
[![Remnawave](https://img.shields.io/badge/Remnawave-3.2%2B-00A8E8)](https://github.com/remnawave/remnawave)
[![Telegram](https://img.shields.io/badge/Telegram-%40remna_shop-2CA5E0?logo=telegram&logoColor=white)](https://t.me/remna_shop)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](https://github.com/elcrazycol/remnatrishop/pulls)

**Remnatrishop** — Telegram bot for selling VPN subscriptions, integrated with the
[Remnawave](https://github.com/remnawave/remnawave) panel.

A continuation of [snoups/remnashop](https://github.com/snoups/remnashop) with:

- ✅ **Support for Remnawave 3.2+** (numeric user IDs, `remnapy 3.2.1`)
- ✅ **Ready-made Docker image** — `ghcr.io/elcrazycol/remnatrishop:dev`, rebuilt on every push
- ✅ **Painless migration** from upstream Remnashop — subscriptions are re-linked automatically
- ✅ All upstream features: trials, grace mode, promocodes, multiple payment gateways,
  web cabinet, HWID limits, squads, referral system and more

---

## ✨ Features

- 🎁 Trial and paid subscriptions, **grace mode** for expired users
- 💳 Payment gateways: Telegram Stars, CryptoBot, UrlPay, MulenPay, RollyPay,
  Robokassa, UnitPay, Valutix and more
- 🏷 Promocodes, giveaways, ad-link attribution, referral system
- 📊 Full Telegram dashboard: users, plans, gateways, notifications, menu editor
- 🖥 Web cabinet with subscription management and password reset
- 📱 HWID device limits, traffic limits, xray squads, link reissue
- 🔔 Notifications: expiring, expired, limited, first connection, torrent blocker
- 🛡 Blacklist domain blocking, anti-abuse rules, channel membership checks
- 🗄 Automatic DB migrations on startup + legacy subscription re-link

---

## 🚀 Quick start

> Requires Remnawave panel **3.2 or newer** and a **Telegram bot** from
> [@BotFather](https://t.me/BotFather).

1. Copy `.env.example` to `.env` and fill in the values (bot token, panel URL/token, DB password).
2. Use the ready-made image — add this to your `docker-compose.yml`:

```yaml
services:
  remnatrishop:
    image: ghcr.io/elcrazycol/remnatrishop:dev
    env_file: .env
    restart: unless-stopped
    volumes:
      - ./logs:/opt/remnatrishop/logs
      - ./assets:/opt/remnatrishop/assets
      - ./backups:/opt/remnatrishop/backups
```

3. `docker compose up -d` — migrations apply automatically, the bot connects to the panel.

See `docker-compose.prod.external.yml` / `docker-compose.prod.internal.yml` for full
production examples (with PostgreSQL and Redis).

---

## 🔁 Migrating from Remnashop (upstream)

Already running the original [snoups/remnashop](https://github.com/snoups/remnashop)?
Here's how to switch without losing subscriptions.

### Why migrate?

Upstream Remnashop was built for Remnawave **2.x** (`remnapy 2.7.0`). Remnawave **3.2+**
removed the `uuid` field from the user API, so the old SDK fails on every user
create/fetch — subscriptions stop being issued. Remnatrishop fixes this.

### Step 1 — Back up

```bash
docker exec <db-container> pg_dump -U <user> <db> > remnatrishop-backup.sql
```
or simply copy your docker volume. Keep the backup until the switch is verified.

### Step 2 — Upgrade the panel to 3.2+

Remnawave **3.2+ is required** (the new SDK doesn't speak to 2.x panels). Users are
preserved during the panel upgrade — that's what the re-link relies on.

### Step 3 — Swap the image

In your `docker-compose.yml` change exactly one line:

```diff
- image: ghcr.io/snoups/remnashop:latest
+ image: ghcr.io/elcrazycol/remnatrishop:dev
```

`.env` and volumes stay untouched — the environment variables are compatible.

### Step 4 — Start and let it migrate

```bash
docker compose up -d
```

On the first start Remnatrishop will:

1. **Apply DB migrations** automatically, including the `0047` migration that converts
   `subscriptions.user_remna_id` from the old UUID column to numeric IDs. Legacy rows
   are temporarily marked with the `REMNA_ID_UNLINKED` sentinel (`-1`) instead of failing.
2. **Re-link subscriptions** — a built-in `SubscriptionRelinker` looks up each legacy
   subscription in the panel by its deterministic username (`rs_<telegram_id>`) and
   stores the new numeric user ID.
3. **Expire orphaned subscriptions** — if a panel user no longer exists, the
   subscription is marked `EXPIRED` and a warning is written to the log, so you can
   see exactly which users need attention.

### Step 5 — Verify

```bash
docker compose logs -f remnatrishop
```

You should see lines like:

```
Found 'N' subscription(s) without a linked panel user, re-linking them by username
Re-linked subscription '12' of user '123456789' to panel user '17'
```

Users keep their subscriptions, traffic and devices. Done. 🎉

---

## 🐳 Docker image

| Tag | Description |
| --- | --- |
| `ghcr.io/elcrazycol/remnatrishop:dev` | Latest development build — rebuilt on every push to `dev` / `fix/remnawave-3.2-compat` |
| `ghcr.io/elcrazycol/remnatrishop:dev-<sha>` | Pinned build for a specific commit |

Images are multi-arch (`linux/amd64`, `linux/arm64`) and public — pullable without
any credentials.

---

## ⚙️ Configuration

All configuration lives in environment variables — see [`.env.example`](.env.example)
for the full list with comments. The most important ones:

| Variable | Purpose |
| --- | --- |
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `REMNAWAVE_HOST` | Remnawave panel host |
| `REMNAWAVE_TOKEN` | Remnawave API token |
| `DATABASE_PASSWORD` | PostgreSQL password |
| `REDIS_PASSWORD` | Redis password |

---

## 🛠 Development

```bash
git clone https://github.com/elcrazycol/remnatrishop.git
cd remnatrishop
uv sync
uv run taskiq scheduler src.infrastructure.taskiq.scheduler:scheduler --tasks-pattern src/infrastructure/taskiq/tasks/*.py -fsd &
uv run taskiq worker src.infrastructure.taskiq.worker:worker --workers 1 --ack-type when_received --tasks-pattern src/infrastructure/taskiq/tasks/*.py -fsd &
uv run uvicorn --factory src.__main__:application --host 0.0.0.0 --port 5000
```

Checks:

```bash
uv run ruff check src
uv run ruff format --check src
uv run mypy src
```

---

## 📄 License

[MIT](LICENSE) © 2024 [snoups](https://github.com/snoups) · 2026 [elcrazycol](https://github.com/elcrazycol)

Remnatrishop is a fork of [snoups/remnashop](https://github.com/snoups/remnashop).
