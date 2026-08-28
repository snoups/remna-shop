# 🛍 Remnatrishop

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/github/license/elcrazycol/remnatrishop)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-ghcr.io%2Felcrazycol%2Fremnatrishop-2496ED?logo=docker&logoColor=white)](https://github.com/elcrazycol/remnatrishop/pkgs/container/remnatrishop)
[![Remnawave](https://img.shields.io/badge/Remnawave-3.2%2B-00A8E8)](https://github.com/remnawave/remnawave)
[![Telegram](https://img.shields.io/badge/Telegram-%40remna_shop-2CA5E0?logo=telegram&logoColor=white)](https://t.me/remna_shop)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](https://github.com/elcrazycol/remnatrishop/pulls)

**Remnatrishop** — Telegram-бот для продажи VPN-подписок, интегрированный с панелью
[Remnawave](https://github.com/remnawave/remnawave).

Продолжение проекта [snoups/remnashop](https://github.com/snoups/remnashop) с:

- ✅ **Поддержкой Remnawave 3.2+** (числовые ID пользователей, `remnapy 3.2.1`)
- ✅ **Готовым Docker-образом** — `ghcr.io/elcrazycol/remnatrishop:dev`, пересобирается при каждом пуше
- ✅ **Безболезненным переездом** с оригинального Remnashop — подписки перелинковываются автоматически
- ✅ Всеми фичами апстрима: триалы, grace-режим, промокоды, платежные шлюзы,
  веб-кабинет, HWID-лимиты, сквады, реферальная система и многое другое

---

## ✨ Возможности

- 🎁 Пробные и платные подписки, **grace-режим** для истёкших пользователей
- 💳 Платёжные шлюзы: Telegram Stars, CryptoBot, UrlPay, MulenPay, RollyPay,
  Robokassa, UnitPay, Valutix и другие
- 🏷 Промокоды, розыгрыши, рекламные ссылки, реферальная система
- 📊 Полный дашборд в Telegram: пользователи, тарифы, шлюзы, уведомления, редактор меню
- 🖥 Веб-кабинет с управлением подпиской и сбросом пароля
- 📱 HWID-лимиты устройств, лимиты трафика, xray-сквады, перевыпуск ссылки
- 🔔 Уведомления: истечение, лимиты, первое подключение, торрент-блокер
- 🛡 Блокировка доменов по черному списку, защита от злоупотреблений, проверка канала
- 🗄 Автоматические миграции БД при старте + перелинковка старых подписок

---

## 🚀 Быстрый старт

> Требуется панель Remnawave **3.2 или новее** и **Telegram-бот** от
> [@BotFather](https://t.me/BotFather).

1. Скопируйте `.env.example` в `.env` и заполните значения (токен бота, URL/токен панели, пароль БД).
2. Используйте готовый образ — добавьте в свой `docker-compose.yml`:

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

3. `docker compose up -d` — миграции применятся автоматически, бот подключится к панели.

Полные продакшн-примеры (с PostgreSQL и Redis) — в `docker-compose.prod.external.yml`
и `docker-compose.prod.internal.yml`.

---

## 🔁 Переезд с Remnashop (оригинала)

Уже работаете на оригинальном [snoups/remnashop](https://github.com/snoups/remnashop)?
Вот как перейти без потери подписок.

### Зачем переезжать?

Оригинальный Remnashop создавался под Remnawave **2.x** (`remnapy 2.7.0`). Remnawave **3.2+**
убрала поле `uuid` из API пользователей, поэтому старый SDK падает при каждом создании/получении
пользователя — подписки перестают выдаваться. Remnatrishop это исправляет.

### Шаг 1 — Бэкап

```bash
docker exec <db-container> pg_dump -U <user> <db> > remnatrishop-backup.sql
```
или просто скопируйте docker-том. Держите бэкап до подтверждения, что всё работает.

### Шаг 2 — Обновите панель до 3.2+

**Remnawave 3.2+ обязательна** (новый SDK не работает с панелями 2.x). Пользователи при
обновлении панели сохраняются — именно на этом основана перелинковка.

### Шаг 3 — Поменяйте образ

В своём `docker-compose.yml` измените ровно одну строку:

```diff
- image: ghcr.io/snoups/remnashop:latest
+ image: ghcr.io/elcrazycol/remnatrishop:dev
```

`.env` и тома не трогаем — переменные окружения совместимы.

### Шаг 4 — Запустите и дайте миграции отработать

```bash
docker compose up -d
```

При первом старте Remnatrishop:

1. **Применит миграции БД** автоматически, включая миграцию `0047`, которая переводит
   `subscriptions.user_remna_id` из старого UUID в числовой ID. Старые строки временно
   помечаются sentinel-значением `REMNA_ID_UNLINKED` (`-1`) вместо падения миграции.
2. **Перелинкует подписки** — встроенный `SubscriptionRelinker` ищет каждую старую
   подписку в панели по детерминированному username (`rs_<telegram_id>`) и сохраняет
   новый числовой ID пользователя.
3. **Погасит осиротевшие подписки** — если пользователя в панели больше нет, подписка
   помечается `EXPIRED`, а в лог пишется предупреждение — вы увидите, кому нужна помощь.

### Шаг 5 — Проверка

```bash
docker compose logs -f remnatrishop
```

В логах должны появиться строки вроде:

```
Found 'N' subscription(s) without a linked panel user, re-linking them by username
Re-linked subscription '12' of user '123456789' to panel user '17'
```

Пользователи сохраняют подписки, трафик и устройства. Готово. 🎉

---

## 🐳 Docker-образ

| Тег | Описание |
| --- | --- |
| `ghcr.io/elcrazycol/remnatrishop:dev` | Последняя dev-сборка — пересобирается при каждом пуше в `dev` / `fix/remnawave-3.2-compat` |
| `ghcr.io/elcrazycol/remnatrishop:dev-<sha>` | Сборка, закреплённая за конкретным коммитом |

Образы мультиархитектурные (`linux/amd64`, `linux/arm64`) и публичные — тянутся без авторизации.

---

## ⚙️ Конфигурация

Вся настройка — через переменные окружения, полный список с комментариями в
[`.env.example`](.env.example). Самые важные:

| Переменная | Назначение |
| --- | --- |
| `BOT_TOKEN` | Токен Telegram-бота от @BotFather |
| `REMNAWAVE_HOST` | Хост панели Remnawave |
| `REMNAWAVE_TOKEN` | API-токен панели Remnawave |
| `DATABASE_PASSWORD` | Пароль PostgreSQL |
| `REDIS_PASSWORD` | Пароль Redis |

---

## 🛠 Разработка

```bash
git clone https://github.com/elcrazycol/remnatrishop.git
cd remnatrishop
uv sync
uv run taskiq scheduler src.infrastructure.taskiq.scheduler:scheduler --tasks-pattern src/infrastructure/taskiq/tasks/*.py -fsd &
uv run taskiq worker src.infrastructure.taskiq.worker:worker --workers 1 --ack-type when_received --tasks-pattern src/infrastructure/taskiq/tasks/*.py -fsd &
uv run uvicorn --factory src.__main__:application --host 0.0.0.0 --port 5000
```

Проверки:

```bash
uv run ruff check src
uv run ruff format --check src
uv run mypy src
```

---

## 📄 Лицензия

[MIT](LICENSE) © 2024 [snoups](https://github.com/snoups) · 2026 [elcrazycol](https://github.com/elcrazycol)

Remnatrishop — форк [snoups/remnashop](https://github.com/snoups/remnashop).
