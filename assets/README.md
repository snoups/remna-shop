# `Banners`

The `banners/` folder in your **user volume** contains your custom banner images. The bot ships default banners baked into the Docker image at `assets.default/banners/`.

## Banner configuration

* **`BOT_USE_BANNERS`**: Set to `true` to enable banners, or `false` to disable them.

## How it works

When loading a banner, the system searches in the following order:

**User volume (`assets/banners/`):**
1. `banners/{user_locale}/{page}` — page-specific banner for the user’s locale
2. `banners/{user_locale}/default` — default banner for the user’s locale
3. `banners/{default_locale}/{page}` — page-specific banner for the default locale
4. `banners/{default_locale}/default` — default banner for the default locale
5. `banners/default` — global user fallback

**Bot defaults (`assets.default/banners/`, inside image):**
6. `banners/{user_locale}/{page}` — bot default page banner
7. `banners/default` — bot global default (last resort)

To **use your own banner** — place the file in `assets/banners/`. It automatically takes priority over the bot’s built-in defaults.

To **use the bot’s shipped defaults** — simply don’t place a file; the image provides it.

## Locale support

Banner filenames must correspond to the predefined names in `/remnashop/src/core/enums.py` as `BannerName`:

* **`DEFAULT`**: The default banner, used when a specific banner is not found.
* **`MENU`**: The main menu banner.
* **`DASHBOARD`**: The dashboard banner.
* **`SUBSCRIPTION`**: The subscription banner.
* **`REFERRAL`**: The referral banner.

## Supported formats

The following file formats are supported (`BannerFormat` in `/remnashop/src/core/enums.py`):

* **JPG**, **JPEG**, **PNG**, **GIF**, **WEBP**


# `Translations`

The `translations/` folder in your **user volume** contains only `custom.ftl` files — one per locale. Bot built-in translations live inside the Docker image at `assets.default/translations/` and are always up to date with the bot version.

## How it works

For each locale, the bot loads two sources in priority order:

1. `assets/translations/{locale}/custom.ftl` — **your overrides** (highest priority)
2. `assets.default/translations/{locale}/*.ftl` — **bot built-ins** (fallback for all other keys)

This means:
- New keys added in a bot update are available automatically — no action needed.
- Your overrides in `custom.ftl` are never touched by updates.
- To override any built-in key, add it to `custom.ftl` with your translation.

## Translation configuration

* **`APP_LOCALES`**: Supported locales (e.g. `ru,en`).
* **`APP_DEFAULT_LOCALE`**: Default locale.


## Key naming convention

All translation keys must follow a unified structure:
```
{category}-{scope}-{entity}-{action-or-state}
```

## Components

| Part                | Description                   | Example                                                                            |
| ------------------- | ----------------------------- | ---------------------------------------------------------------------------------- |
| `{category}`        | Top-level type of text        | `btn`, `msg`, `ntf`                                                                |
| `{scope}`           | Logical group or subsystem    | `user`, `plan`, `broadcast`, `gateway`, `subscription`, `access`, `error`, `event` |
| `{entity}`          | Specific object or sub-entity | `content`, `payment`, `link`, `node`                                               |
| `{action-or-state}` | Action or state, in lowercase | `created`, `deleted`, `empty`, `invalid`, `failed`, `not-found`                    |

## Naming rules

1. Use lowercase with hyphens (-) — no underscores or spaces.
2. Follow the order:
    ```
    category → scope → entity → action/state
    ```
    - ✅ ntf-broadcast-content-empty
    - ✅ btn-user-create
    - ✅ msg-plan-deleted-success

    - ❌ ntf-content-empty-broadcast
    - ❌ btn-create-user
    - ❌ msg-plan-success-deleted
3. Actions — past tense verbs (created, updated, deleted, canceled, failed).
4. States — adjectives (empty, invalid, not-found, expired, not-available).
5. Limit to 5 segments maximum (recommended).
6. Keep the total key length under 32 characters (recommended).

## Examples keys

| Purpose                               | Key                               |
| ------------------------------------- | --------------------------------- |
| Notification: user expired            | `ntf-user-expired`                |
| Notification: broadcast empty content | `ntf-broadcast-content-empty`     |
| Button: confirm deletion              | `btn-plan-confirm-delete`         |
| Message: plan created successfully    | `msg-plan-created-success`        |
| Notification: gateway test failed     | `ntf-gateway-test-payment-failed` |


## `custom.ftl`

Each locale folder may contain a `custom.ftl` file (e.g. `translations/ru/custom.ftl`). This file is intended for user-defined translations that are not part of the standard set — such as custom menu buttons, plan names, and similar entries.

### Usage

Add key-value pairs to the file using the standard Fluent syntax:

```
key-name = Translation text
```

Then use the key wherever text is expected (e.g. in a plan name or menu link). The system will resolve it to the translated string at runtime.

### Constraints

| Context      | Max length      |
| ------------ | --------------- |
| Buttons      | 32 characters   |
| Messages     | 1024 characters |

### Key naming

Keys must be **unique** and should follow the general naming convention described above. To avoid collisions with built-in keys, prefix custom keys with `custom-`:

```
custom-menu-link1 = 1️⃣ First button
custom-plan-name1 = Basic plan
```

### Example file

```ftl
# Custom menu buttons
custom-menu-link1 = 1️⃣ First button
custom-menu-link2 = 2️⃣ Second button

# Custom plan names
custom-plan-name1 = 1️⃣ Basic plan
custom-plan-name2 = 2️⃣ Premium plan
```


# `Custom Emoji`

Telegram supports custom emoji in buttons. To use them, the bot must have a paid username (Fragment) or the bot owner must have an active Telegram Premium subscription.

## How to get an emoji ID

1. Send the desired custom emoji to [@getidsbot](https://t.me/getidsbot) or `@RawDataBot`.
2. The bot will return message details including the `custom_emoji_id`.

## Syntax

Two formats are supported directly in `.ftl` key values.

### Full format

```ftl
btn-example = <tg-emoji emoji-id="5406756500108501710">🎁</tg-emoji> Button text
```

### Short format

```ftl
btn-example = <e id="5406756500108501710">🎁</e> Button text
```

The fallback text inside the tag (a plain emoji) is shown on clients that don't support custom emoji. It is recommended to always provide it.

## Usage in buttons

Both formats are automatically recognized for **every** keyboard button, regardless of the widget used. The tag is processed globally in `MessageManager.show_message` before the message is sent: the custom emoji is extracted from the key text and passed as `icon_custom_emoji_id` on the Telegram button — it is a separate field, not part of the label.

Example in `buttons.ftl`:

```ftl
btn-menu =
    .connect = <tg-emoji emoji-id="5447410659077661506">🚀</tg-emoji> Connect
    .devices = <e id="5271604874419647061">📱</e> Devices
```

## Usage in messages

Custom emoji can be used in message text via the `I18nFormat` widget. The short format `<e id="...">` is automatically expanded to the full `<tg-emoji>` tag before the text is sent.

```ftl
msg-broadcast-main = <tg-emoji emoji-id="5424818078833715060">📢</tg-emoji> <b>Broadcast</b>
msg-statistics-main = <e id="5231200819986047254">📊</e> <b>Statistics</b>
```

## Emoji priority

If a button already has `icon_custom_emoji_id` set via the widget's `Style` (aiogram-dialog `Style(icon_custom_emoji_id="...")`), it takes priority over the emoji from the key text.

---

# `Button Color`

Telegram inline buttons support a `style` (color): `primary`, `success`, `danger`. It can be set directly from a `.ftl` key value via the `<c>` tag, applied globally to every keyboard button (same mechanism as custom emoji).

## Syntax

```ftl
btn-buy = <c>success</c>🛒 Buy
btn-cancel = <c>danger</c>Cancel
```

The tag is stripped from the label and mapped to the button's `style` field. It can be combined with a custom emoji tag on the same button.

## Color priority

Unlike custom emoji, a color from the key text **overrides** any `Style(ButtonStyle.…)` set in Python code. This lets translations recolor buttons without touching handlers. Reply-keyboard buttons don't support colors — the tag is simply stripped there.

---

# `QR Code Logo`

You can customize the appearance of the generated invitation QR code by adding your logo to the center of the code.

* **Path:** `assets/logo.png`
* **Purpose:** If this file exists, the system will use it as a logo, overlaying it in the center of the generated QR code image for branding purposes.
* **Format:** The logo must be a `PNG` file, preferably with a transparent background.