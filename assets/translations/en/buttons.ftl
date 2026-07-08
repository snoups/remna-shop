btn-back =
    .general = ⬅️ Back
    .menu = ↩️ Main menu
    .menu-return = ↩️ Return to main menu
    .dashboard = ↩️ Return to dashboard
    .referrals = 👪 To referral list

btn-common =
    .notification-close = ❌ Close
    .devices-empty = ⚠️ You have no connected devices
    .cancel = Cancel
    .next = ▶️ Next
    .prev = ◀️ Back

    .squad-choice = { $selected ->
    [1] 🔘
    *[0] ⚪
    } { $name }

    .duration = ⌛ { $value ->
    [0] { unlimited }
    *[OTHER] { unit-day }
    }

btn-devices =
    .delete-all = 🗑 Delete all devices
    .reissue = 🔄 Reissue subscription
    .confirm-delete = ✅ Yes, delete
    .confirm-reissue = ✅ Yes, reset
    .cancel-reissue = ❌ No

    .item = { $platform_icon } { $platform } { $device_model ->
    [0] { space }
    *[HAS] ({ $device_model }){ space }
    }— { $created_at }

btn-backup =
    .active-toggle = { $enabled ->
        [1] 🟢 Enabled
        *[0] 🔴 Disabled
    }
    .set-interval = 🕐 Interval
    .set-max-files = 📁 File count
    .send-toggle = { $send_to_chat ->
        [1] ✅ Send to chat: enabled
        *[0] ❌ Send to chat: disabled
    }
    .backup-assets = 📦 Run assets backup
    .backup-db = 🗄 Run database backup

btn-remnashop-info =
    .release-latest = 👀 View
    .how-upgrade = ❓ How to update
    .github = ⭐ GitHub
    .telegram = 👪 Telegram
    .donate = 💰 Support the developer
    .docs = 📖 Documentation

btn-requirement =
    .rules-accept = ✅ Accept rules
    .channel-join = ❤️ Go to channel
    .channel-confirm = ✅ Confirm

btn-menu =
    .trial = 🎁 TRY FOR FREE
    .trial-paid = 🚀 TRY FOR { $trial_price }
    .connect = 🚀 Connect
    .connect-reserve = 🔗 Connect (reserve)
    .devices = 📱 Devices
    .subscription = 💳 Subscription
    .invite = 👥 Invite
    .support = 🆘 Support
    .web-cabinet = 🌐 Web cabinet
    .dashboard = 🛠 Dashboard

    .connect-not-available =
    ⚠️ { $status ->
    [LIMITED] TRAFFIC LIMIT EXCEEDED
    [EXPIRED] SUBSCRIPTION EXPIRED
    *[OTHER] YOUR SUBSCRIPTION IS NOT WORKING
    } ⚠️

btn-invite =
    .about = ❓ More about the reward
    .copy = 📋 Copy link
    .send = 📩 Invite
    .qr = 🧾 QR code
    .withdraw-points = 💎 Exchange points
    .reset-referral = 🔄 Reset referral link

btn-dashboard =
    .statistics = 📊 Statistics
    .users = 👥 Users
    .broadcast = 📢 Broadcast
    .promocodes = 🎟 Promo codes
    .access = 🔓 Access mode
    .remnawave = 🌊 RemnaWave
    .remnashop = 🛍 RemnaShop
    .transactions = 🧾 Transactions
    .importer = 📥 Import users

btn-statistics =
    .users = 👥 Users
    .subscriptions = 💳 Subscriptions
    .transactions = 🧾 Transactions
    .promocodes = 🎁 Promo codes
    .referrals = 👪 Referrals

    .subscription-page =
    { $page ->
        [0] { $is_current ->
            [1] [ General statistics ]
            *[0] General statistics
        }
        *[OTHER] { $is_current ->
            [1] [ { $plan_name } ]
            *[0] { $plan_name }
        }
    }

    .transaction-page =
    { $page ->
        [0] { $is_current ->
            [1] [ General statistics ]
            *[0] General statistics
        }
        *[OTHER] { $is_current ->
            [1] [ { gateway-type } ]
            *[0] { gateway-type }
        }
    }

btn-users =
    .search = 🔍 Search user
    .recent-registered = 🆕 Recently registered
    .recent-activity = 📝 Recently active
    .blacklist = 🚫 Blacklist
    .unblock-all = 🔓 Unblock all
    .blacklist-view = 🗒️ Blocked list
    .blacklist-block = ⛔ Block by ID
    .blacklist-sources = 🔗 Auto-updated lists
    .blacklist-sources-sync = 🔄 Synchronize
    .blacklist-block-clear = 🗑 Clear ID list

    .blacklist-source = 🔗 { $source }

btn-user =
    .discount = 💸 Discount
    .discount-personal = 👤 Personal discount
    .discount-purchase = 🎟 On next purchase
    .points = 💎 Points
    .statistics = 📊 Statistics
    .referrals = 👪 Referrals
    .message = 📩 Message
    .role = 👮‍♂️ Role
    .transactions = 🧾 Transactions
    .give-access = 🔑 Plan access
    .current-subscription = 💳 Current subscription
    .subscription-traffic-limit = 🌐 Traffic limit
    .subscription-device-limit = 📱 Device limit
    .subscription-expire-time = ⏳ Expiration time
    .subscription-squads = 🔗 Squads
    .subscription-traffic-reset = 🔄 Reset traffic
    .subscription-devices = 🗒️ Device list
    .subscription-url = 📋 Copy link
    .subscription-delete = ❌ Delete
    .subscription-reissue = ♻️ Reissue
    .message-preview = 👀 Preview
    .message-confirm = ✅ Send
    .referral-reset = 🔄 Reset referral link
    .sync = 🌀 Synchronize
    .sync-remnawave = 🌊 Use Remnawave data
    .sync-remnashop = 🛍 Use Remnashop data
    .give-subscription = 🎁 Grant subscription
    .subscription-internal-squads = ⏺️ Internal squads
    .subscription-external-squads = ⏹️ External squad

    .allowed-plan-choice = { $selected ->
    [1] 🔘
    *[0] ⚪
    } { $plan_name }

    .subscription-active-toggle = { $is_active ->
    [1] 🔴 Disable
    *[0] 🟢 Enable
    }

    .transaction = { $status ->
    [PENDING] 🕓
    [COMPLETED] ✅
    [CANCELED] ❌
    [REFUNDED] 💸
    [FAILED] ⚠️
    *[OTHER] { $status }
    } { $created_at } · { gateway-type }

    .trial-toggle = { $is_trial_available ->
    [1] 🧪 Trial: available
    *[0] 🧪 Trial: not available
    }

    .block = { $is_blocked ->
    [1] 🔓 Unblock
    *[0] 🔒 Block
    }

btn-broadcast =
    .list = 🗒️ List all broadcasts
    .all = 👥 Everyone
    .plan = 📦 By plan
    .subscribed = ✅ With subscription
    .unsubscribed = ❌ Without subscription
    .expired = ⌛ Expired
    .trial = ✳️ With trial
    .content = ✉️ Edit content
    .buttons = ✳️ Edit buttons
    .preview = 👀 Preview
    .confirm = ✅ Start broadcast
    .refresh = 🔄 Refresh data
    .cancel = ⛔ Stop broadcast
    .delete = ❌ Delete sent

    .plan-title = { $is_active ->
    [1] 🟢
    *[0] 🔴
    } { $name }

    .button-choice = { $selected ->
    [1] 🔘
    *[0] ⚪
    }

    .title = { $status ->
    [PROCESSING] ⏳
    [COMPLETED] ✅
    [CANCELED] ⛔
    [DELETED] ❌
    [ERROR] ⚠️
    *[OTHER] { $status }
    } { $created_at }

btn-goto =
    .subscription = 💳 Buy subscription
    .promocode = 🎟 Activate promo code
    .invite = 👥 Invite
    .subscription-renew = 🔄 Renew subscription
    .user-profile = 👤 Go to user
    .referrer-profile = 🤝 Go to inviter
    .contact-support = 📩 Go to support

btn-promocodes =
    .save = ✅ Save
    .create = 🆕 Create promo code
    .confirm = ✅ Create promo code
    .delete = 🗑️ Delete
    .regenerate = 🔄 Regenerate
    .code = 🏷️ Code
    .type = 🔖 Reward type
    .availability = ✴️ Access
    .reward = 🎁 Reward
    .plan = 📦 Plan
    .expires = ⌛ Expiration
    .max-activations = 🔢 Activation limit
    .reset = 🔄 Reset

    .plan-duration = { $days ->
        [one] { $days } day
        *[other] { $days } days
    }

    .item = 🎟 { $code } — { promocode-type }

    .active-toggle = { $is_active ->
    [1] 🟢 Enabled
    *[0] 🔴 Disabled
    }

    .reusable-toggle = 🔁 { $is_reusable ->
    [1] Reusable: yes
    *[0] Reusable: no
    }

btn-access =
    .mode = { access-mode }
    .conditions = ⚙️ Access conditions
    .rules = ✳️ Rules acceptance
    .channel = ❇️ Channel subscription

    .payments-toggle = { $enabled ->
    [1] 🔘
    *[0] ⚪
    } Payments

    .registration-toggle = { $enabled ->
    [1] 🔘
    *[0] ⚪
    } Registration

    .condition-toggle = { $enabled ->
    [1] 🔘 Enabled
    *[0] ⚪ Disabled
    }

btn-remnashop =
    .admins = 👮‍♂️ Admins
    .gateways = 🌐 Payment systems
    .referral = 👥 Referral system
    .advertising = 🎯 Advertising
    .plans = 📦 Plans
    .notifications = 🔔 Notifications
    .logs = 📄 Logs
    .menu-editor = 🎛 Main menu editor
    .backup = 💾 Backup
    .extra = ⚙️ Extra settings

btn-remnashop-transaction = { $status ->
    [PENDING] 🕓
    [COMPLETED] ✅
    [CANCELED] ❌
    [REFUNDED] 💸
    [FAILED] ⚠️
    *[OTHER] { $status }
    } #{ $user_id } · { gateway-type } · { $created_at }

btn-remnashop-extra =
    .device-single = { $enabled ->
        [1] 🟢
        *[0] 🔴
    } Device deletion

    .device-all = { $enabled ->
        [1] 🟢
        *[0] 🔴
    } Delete all devices

    .link-reset = { $enabled ->
        [1] 🟢
        *[0] 🔴
    } Subscription reissue
    .referral-reset = { $enabled ->
        [1] 🟢
        *[0] 🔴
    } Referral link reset

    .trial-channel-guard = { $enabled ->
        [1] 🟢
        *[0] 🔴
    } Auto-disable trial

    .mini-app-reserve = { $enabled ->
        [1] 🟢
        *[0] 🔴
    } Reserve connect button

    .toggle = { $enabled ->
        [1] 🟢 Enabled
        *[0] 🔴 Disabled
    }

btn-menu-editor =
    .text = 🏷️ Text
    .availability = ✴️ Access
    .type = 🔖 Type
    .payload = 📄 Data
    .color = 🎨 Color
    .confirm = ✅ Save
    .color-default = No color
    .color-primary = Primary
    .color-success = Green
    .color-danger = Red

    .button = { $is_active ->
        [1] 🟢
        *[0] 🔴
    } { $text }

    .active-toggle = { $is_active ->
        [1] 🟢 Enabled
        *[0] 🔴 Disabled
    }

    .subscribers-only-toggle = { $subscribers_only ->
        [1] 💳 With subscription
        *[0] 👥 Everyone
    }

btn-gateway =
    .title = { gateway-type }
    .setting = { $field }
    .display-name = 🏷️ Display name
    .webhook-copy = 📋 Copy webhook
    .test = 🐞 Test
    .default-currency = 💸 Default currency
    .placement = 🔢 Change positioning
    .field-reset = ♻️ Reset value

    .active-toggle = { $is_active ->
    [1] 🟢 Enabled
    *[0] 🔴 Disabled
    }

    .default-currency-choice = { $enabled ->
    [1] 🔘
    *[0] ⚪
    } { $symbol } { $currency }

btn-referral =
    .level = 🔢 Level
    .reward-type = 🎀 Reward type
    .accrual-strategy = 📍 Accrual condition
    .reward-strategy = ⚖️ Accrual form
    .reward = 🎁 Reward

    .active-toggle = { $is_enable ->
    [1] 🟢 Enabled
    *[0] 🔴 Disabled
    }

    .level-choice = { $type ->
    [1] 1️⃣
    [2] 2️⃣
    [3] 3️⃣
    *[OTHER] { $type }
    }

    .reward-choice = { $type ->
    [POINTS] 💎 Points
    [EXTRA_DAYS] ⏳ Days
    *[OTHER] { $type }
    }

    .accrual-strategy-choice = { $type ->
    [ON_FIRST_PAYMENT] 💳 First payment
    [ON_EACH_PAYMENT] 💸 Each payment
    *[OTHER] { $type }
    }

    .reward-strategy-choice = { $type ->
    [AMOUNT] 🔸 Fixed
    [PERCENT] 🔹 Percentage
    *[OTHER] { $type }
    }

btn-notifications =
    .user = 👥 User
    .system = ⚙️ System
    .route = 📡 Route
    .default-route = 📡 General route
    .chat-id = 💬 Change chat
    .thread-id = 📁 Change thread
    .route-clear = ❌ Delete route

    .user-choice = { $enabled ->
    [1] 🔘
    *[0] ⚪
    } { notification-type }

    .system-choice = { $enabled ->
    [1] 🔘
    *[0] ⚪
    } { $has_route ->
    [1] 📡
    *[0] { space }
    } { notification-type }

    .active-toggle = { $is_active ->
    [1] 🟢 Enabled
    *[0] 🔴 Disabled
    }

btn-plans =
    .save = ✅ Save
    .create = 🆕 Create plan
    .create-confirm = ✅ Create plan
    .delete = ❌ Delete
    .name = 🏷️ Name
    .description = 💬 Description
    .description-remove = ❌ Remove current description
    .tag = 📌 Tag
    .tag-remove = ❌ Remove current tag
    .type = 🔖 Type
    .availability = ✴️ Access
    .durations-prices = ⏳ Durations and 💰 Prices
    .traffic = 🌐 Traffic
    .devices = 📱 Devices
    .allowed = 👥 Allowed users
    .squads = 🔗 Squads
    .internal-squads = ⏺️ Internal squads
    .external-squads = ⏹️ External squad
    .duration-add = 🆕 Add duration
    .price-choice = 💸 { $price } { $currency }
    .export = 📤 Export
    .import = 📥 Import
    .exporting = 📤 Export
    .importing = 📥 Import
    .url = 📋 Copy plan link

    .trial = { $is_trial ->
    [1] 🔘
    *[0] ⚪
    } Trial

    .export-choice = { $selected ->
    [1] 🔘
    *[0] ⚪
    } { $name }

    .title = { $is_active ->
    [1] 🟢
    *[0] 🔴
    } { $name }

    .active-toggle = { $is_active ->
    [1] 🟢 Enabled
    *[0] 🔴 Disabled
    }

    .type-choice = { $type ->
    [TRAFFIC] 🌐 Traffic
    [DEVICES] 📱 Devices
    [BOTH] 🔗 Traffic + devices
    [UNLIMITED] ♾️ Unlimited
    *[OTHER] { $type }
    }

    .availability-choice = { $type ->
    [ALL] 🌍 For everyone
    [NEW] 🌱 For new
    [EXISTING] 👥 For clients
    [INVITED] ✉️ For invited
    [ALLOWED] 🔐 For allowed
    [LINK] 🔗 By link
    *[OTHER] { $type }
    }

    .traffic-strategy-choice = { $selected ->
    [1] 🔘 { traffic-strategy }
    *[0] ⚪ { traffic-strategy }
    }


btn-remnawave =
    .users = 👥 Users
    .hosts = 🌐 Hosts
    .nodes = 🖥️ Nodes
    .inbounds = 🔌 Inbounds

btn-importer =
    .from-xui = 💩 Import from 3X-UI panel
    .sync-from-panel = 🌀 Sync: panel → bot
    .sync-from-bot = 🤖 Sync: bot → panel
    .sync-start = ▶️ Synchronize
    .squads = 🔗 Internal squads
    .import-all = ✅ Import all
    .import-active = ❇️ Import active

btn-subscription =
    .plan = 💳 Go to subscription checkout
    .new = 💸 Buy subscription
    .renew = 🔄 Renew
    .change = 🔃 Change
    .promocode = 🎟 Activate promo code
    .promocode-confirm = ✅ Confirm
    .pay = 💳 Pay
    .get = 🎁 Get for free
    .back-plans = ⬅️ Back to plan selection
    .back-duration = ⬅️ Change duration
    .back-payment-method = ⬅️ Change payment method
    .connect = 🚀 Connect

    .payment-method = { $gateway_title } | { $final_amount ->
    [0] 🎁
    *[HAS] { $final_amount }{ $currency }
    }

    .duration = { $period } | { $final_amount ->
    [0] 🎁
    *[HAS] { $final_amount }{ $currency }
    }

btn-ad-links =
    .save = ✅ Save
    .create = 🆕 Create link
    .create-confirm = ✅ Create link
    .delete = ❌ Delete link
    .name = 🏷️ Name
    .code = 🔗 Code
    .regenerate = 🔄 Regenerate
    .stats = 📊 Statistics
    .url = 📋 Copy link

    .title = { $is_active ->
    [1] 🟢
    *[0] 🔴
    } { $name }

    .active-toggle = { $is_active ->
    [1] 🟢 Enabled
    *[0] 🔴 Disabled
    }
