space = {" "}
empty = { "!empty!" }
btn-test = Button
msg-test = Message
development = Under development!
test-payment = Test payment
unknown = —
raw-message = { $content }

payment-invoice-description = { purchase-type } of subscription { $name } for { $duration }

ad-link-default-name = New link
plan-default-name = New plan

platform-icon =
    .ios = 🍎
    .android = 🤖
    .windows = 🖥️
    .macos = 💻
    .linux = 🐧
    .default = 📱

inline-invite =
    .title = Invite a friend
    .description = Tap to send an invite link!
    .message =
        🚀 Hi! Want a stable and fast VPN?

        { $bot_name } — will help you with that!

        ↘️ TAP THE BUTTON AND TRY IT FOR FREE!
    .start = 🚀 Join

message =
    .withdraw-points = Hello! I'd like to request a points exchange.
    .paysupport = Hello! I'd like to request a refund.
    .help = Hello! I need help.

command =
    .start = Restart the bot
    .paysupport = Refund
    .rules = Terms of use
    .help = Help

hdr-user = <b>👤 User</b>:
hdr-user-profile = <b>👤 Profile</b>:
hdr-payment = <b>💰 Payment</b>:
hdr-error = <b>⚠️ Error</b>:
hdr-node = <b>🖥 Node</b>:
hdr-hwid = <b>📱 Device</b>:

hdr-subscription = { $is_trial ->
    [1] <b>🎁 Trial subscription</b>:
    *[0] <b>💳 Subscription</b>:
}

hdr-plan = { $is_trial_plan ->
    [1] <b>🎁 Trial plan</b>:
    *[0] <b>📦 Plan</b>:
}

frg-user =
    <blockquote>
    { $telegram_id ->
        [0] • <b>Email</b>: <code>{ $email }</code>
        *[HAS] • <b>ID</b>: <code>{ NUMBER($telegram_id, useGrouping: 0) }</code>
    }
    • <b>Name</b>: { $name }
    { $show_personal_discount ->
    [1] • <b>Personal discount</b>: { $personal_discount }%
    *[0] { empty }
    }
    { $show_purchase_discount ->
    [1] • <b>Purchase discount</b>: { $purchase_discount }%
    *[0] { empty }
    }
    </blockquote>

frg-user-info =
    <blockquote>
    { $telegram_id ->
        [0] • <b>Email</b>: <code>{ $email }</code>
        *[HAS] • <b>ID</b>: <code>{ NUMBER($telegram_id, useGrouping: 0) }</code>
    }
    • <b>Name</b>: { $name } { $username ->
        [0] { empty }
        *[HAS] (<a href="tg://user?id={ $telegram_id }">@{ $username }</a>)
    }
    </blockquote>

frg-user-details =
    <blockquote>
    { $telegram_id ->
        [0] • <b>Email</b>: <code>{ $email }</code>
        *[HAS] • <b>ID</b>: <code>{ NUMBER($telegram_id, useGrouping: 0) }</code>
    }
    • <b>Name</b>: { $name } { $username ->
        [0] { space }
        *[HAS] (<a href="tg://user?id={ $telegram_id }">@{ $username }</a>)
    }
    • <b>Role</b>: { role }
    • <b>Language</b>: { language }
    • <b>Bot blocked</b>: { $is_bot_blocked ->
        [1] Yes
        *[0] No
    }
    { $show_points ->
    [1] • <b>Points</b>: { $points }
    *[0] { empty }
    }
    </blockquote>

frg-subscription =
    <blockquote>
    • <b>Traffic limit</b>: { $traffic_limit }
    • <b>Device limit</b>: { $device_limit }
    • <b>Remaining</b>: { $expire_time }
    </blockquote>

frg-subscription-user-editor =
    <blockquote>
    • <b>Plan</b>: { $plan_name }
    • <b>Traffic limit</b>: { $traffic_limit }
    • <b>Device limit</b>: { $device_limit }
    • <b>Remaining</b>: { $expire_time }
    </blockquote>

frg-subscription-details =
    <blockquote>
    • <b>ID</b>: <code>{ $subscription_id }</code>
    • <b>Status</b>: { subscription-status }
    • <b>Traffic</b>: { $traffic_used } / { $traffic_limit }
    • <b>Device limit</b>: { $device_limit }
    • <b>Remaining</b>: { $expire_time }
    </blockquote>

frg-payment-info =
    <blockquote>
    • <b>ID</b>: <code>{ $payment_id }</code>
    • <b>Payment method</b>: { gateway-type }
    • <b>Amount</b>: { frg-payment-amount }
    </blockquote>

frg-payment-amount = { $final_amount }{ $currency } { $discount_percent ->
    [0] { space }
    *[more] { space } <strike>{ $original_amount }{ $currency }</strike> (-{ $discount_percent }%)
    }

frg-plan-snapshot =
    <blockquote>
    • <b>Plan</b>: <code>{ $plan_name }</code>
    • <b>Type</b>: { plan-type }
    • <b>Traffic limit</b>: { $plan_traffic_limit }
    • <b>Device limit</b>: { $plan_device_limit }
    • <b>Duration</b>: { $plan_duration }
    </blockquote>

frg-plan-snapshot-comparison =
    <blockquote>
    • <b>Plan</b>: <code>{ $previous_plan_name }</code> -> <code>{ $plan_name }</code>
    • <b>Type</b>: { $previous_plan_type } -> { plan-type }
    • <b>Traffic limit</b>: { $previous_plan_traffic_limit } -> { $plan_traffic_limit }
    • <b>Device limit</b>: { $previous_plan_device_limit } -> { $plan_device_limit }
    • <b>Duration</b>: { $previous_plan_duration } -> { $plan_duration }
    </blockquote>

frg-node-info =
    <blockquote>
    • <b>Name</b>: { $country } { $name }
    • <b>Address</b>: <code>{ $address }{ $port ->
    [0] { space }
    *[HAS] :{ $port }
    }</code>
    • <b>Traffic</b>: { $traffic_used } / { $traffic_limit }
    { $last_status_message ->
    [0] { empty }
    *[HAS] • <b>Last status</b>: { $last_status_message }
    }
    { $last_status_change ->
    [0] { empty }
    *[HAS] • <b>Status changed</b>: { $last_status_change }
    }
    </blockquote>

frg-user-hwid =
    <blockquote>
    • <b>HWID</b>: <code>{ $hwid }</code>
    { $platform ->
    [0] { space }
    *[HAS] • <b>Platform</b>: { $platform }
    }
    { $device_model ->
    [0] { space }
    *[HAS] • <b>Model</b>: { $device_model }
    }
    { $os_version ->
    [0] { space }
    *[HAS] • <b>Version</b>: { $os_version }
    }
    { $user_agent ->
    [0] { space }
    *[HAS] • <b>Agent</b>: { $user_agent }
    }
    </blockquote>

frg-build-info =
    { $has_build ->
    [0] { space }
    *[HAS]
    <b>🏗️ Build information</b>:
    <blockquote>
    Build time: { $time }
    Branch: { $branch } ({ $tag })
    Commit: <a href="{ $commit_url }">{ $commit }</a>
    </blockquote>
    }

frg-promocode-reward = { $promocode_type ->
    [DURATION] { $reward ->
        [0] { unlimited } days
        [one] { $reward } day
        *[other] { $reward } days
        } to the current subscription
    [TRAFFIC] { $reward ->
        [0] { unlimited } GB
        *[OTHER] { $reward } GB
        } to the current subscription
    [DEVICES] { $reward ->
        [0] { unlimited } devices
        [one] { $reward } device
        *[other] { $reward } devices
        } to the current subscription
    [SUBSCRIPTION] subscription { $plan_name }
    [PERSONAL_DISCOUNT] { $reward }% to the personal discount
    [PURCHASE_DISCOUNT] { $reward }% to the discount on the next purchase
    *[OTHER] { $reward }
    }

role-owner = Owner
role-dev = Developer
role-admin = Admin
role-preview = Observer
role-user = User
role =
    { $role ->
    [5] { role-owner }
    [4] { role-dev }
    [3] { role-admin }
    [2] { role-preview }
    *[1] { role-user }
}

unlimited = ∞

unit-unlimited = { $value ->
    [0] { unlimited }
    *[OTHER] { $value }
}

unit-device = { $value ->
    [0] { unlimited }
    *[OTHER] { $value }
} { $value ->
    [0] { space }
    [one] device
    *[OTHER] devices
}

unit-byte = { $value } B
unit-kilobyte = { $value } KB
unit-megabyte = { $value } MB
unit-gigabyte = { $value } GB
unit-terabyte = { $value } TB

unit-second = { $value } { $value ->
    [one] second
    *[OTHER] seconds
}

unit-minute = { $value } { $value ->
    [one] minute
    *[OTHER] minutes
}

unit-hour = { $value } { $value ->
    [one] hour
    *[OTHER] hours
}

unit-day = { $value } { $value ->
    [one] day
    *[OTHER] days
}

unit-month = { $value } { $value ->
    [one] month
    *[OTHER] months
}

unit-year = { $value } { $value ->
    [one] year
    *[OTHER] years
}


plan-type = { $plan_type ->
    [TRAFFIC] Traffic
    [DEVICES] Devices
    [BOTH] Traffic + devices
    [UNLIMITED] Unlimited
    *[OTHER] { $plan_type }
}

promocode-type = { $promocode_type ->
    [DURATION] Duration
    [TRAFFIC] Traffic
    [DEVICES] Devices
    [SUBSCRIPTION] Subscription
    [PERSONAL_DISCOUNT] Personal discount
    [PURCHASE_DISCOUNT] Purchase discount
    *[OTHER] { $promocode_type }
}

availability-type = { $availability_type ->
    [ALL] For everyone
    [NEW] For new
    [EXISTING] For existing
    [INVITED] For invited
    [ALLOWED] For allowed
    [LINK] By link
    *[OTHER] { $availability_type }
}

gateway-type = { $gateway_type ->
    [TELEGRAM_STARS] Telegram Stars
    [YOOKASSA] YooKassa
    [YOOMONEY] YooMoney
    [CRYPTOMUS] Cryptomus
    [HELEKET] Heleket
    [CRYPTOPAY] CryptoPay
    [FREEKASSA] FreeKassa
    [MULENPAY] MulenPay
    [PAYMASTER] PayMaster
    [PLATEGA] Platega
    [ROBOKASSA] RoboKassa
    [URLPAY] UrlPay
    [WATA] WATA
    [VALUTIX] Valutix
    *[OTHER] { $gateway_type }
}

access-mode = { $access_mode ->
    [PUBLIC] 🟢 Allowed for everyone
    [INVITED] 🟡 Allowed for invited
    [RESTRICTED] 🔴 Forbidden for everyone
    *[OTHER] { $access_mode }
}

audience-type = { $audience_type ->
    [ALL] Everyone
    [PLAN] By plan
    [SUBSCRIBED] With subscription
    [UNSUBSCRIBED] Without subscription
    [EXPIRED] Expired
    [TRIAL] With trial
    *[OTHER] { $audience_type }
}

broadcast-status = { $broadcast_status ->
    [PROCESSING] In progress
    [COMPLETED] Completed
    [CANCELED] Canceled
    [DELETED] Deleted
    [ERROR] Error
    *[OTHER] { $broadcast_status }
}

transaction-status = { $transaction_status ->
    [PENDING] Pending
    [COMPLETED] Completed
    [CANCELED] Canceled
    [REFUNDED] Refunded
    [FAILED] Error
    *[OTHER] { $transaction_status }
}

subscription-status = { $subscription_status ->
    [ACTIVE] Active
    [DISABLED] Disabled
    [LIMITED] Traffic exhausted
    [EXPIRED] Expired
    [DELETED] Deleted
    *[OTHER] { $subscription_status }
}

purchase-type = { $purchase_type ->
    [NEW] Purchase
    [RENEW] Renewal
    [CHANGE] Change
    *[OTHER] { $purchase_type }
}

traffic-strategy = { $strategy_type ->
    [NO_RESET] On payment
    [DAY] Every day
    [WEEK] Every week
    [MONTH] Every month
    [MONTH_ROLLING] Every month (by creation date)
    *[OTHER] { $strategy_type }
    }

reward-type = { $reward_type ->
    [POINTS] Points
    [EXTRA_DAYS] Days
    *[OTHER] { $reward_type }
    }

accrual-strategy = { $accrual_strategy_type ->
    [ON_FIRST_PAYMENT] First payment
    [ON_EACH_PAYMENT] Each payment
    *[OTHER] { $accrual_strategy_type }
    }

reward-strategy = { $reward_strategy_type ->
    [AMOUNT] Fixed
    [PERCENT] Percentage
    *[OTHER] { $reward_strategy_type }
    }

button-type = { $button_type ->
    [URL] Open link
    [COPY] Copy text
    [WEB_APP] Open web app
    [TEXT] Send message
    *[OTHER] { $button_type }
}

notification-type = { $notification_type ->
    [SYSTEM] System
    [EXPIRES_IN_3_DAYS] Subscription expiring (3 days)
    [EXPIRES_IN_2_DAYS] Subscription expiring (2 days)
    [EXPIRES_IN_1_DAY] Subscription expiring (1 day)
    [EXPIRED] Subscription expired
    [EXPIRED_1_DAY_AGO] Subscription expired (1 day)
    [LIMITED] Traffic exhausted
    [REFERRAL_ATTACHED] Referral attached
    [REFERRAL_REWARD_RECEIVED] Referral reward received
    [REFERRAL_REWARD_FAILED] Reward accrual error
    [BOT_LIFECYCLE] Bot lifecycle
    [BOT_UPDATE] Bot updates
    [USER_REGISTERED] User registration
    [SUBSCRIPTION] Subscription purchase
    [PROMOCODE_ACTIVATED] Promo code activation
    [TRIAL_ACTIVATED] Trial activation
    [NODE_STATUS_CHANGED] Node status
    [NODE_TRAFFIC_REACHED] Node traffic
    [TORRENT_BLOCKER] Torrent detection
    [USER_FIRST_CONNECTION] First connection
    [USER_DEVICES_UPDATED] User devices
    [USER_REVOKED_SUBSCRIPTION] Subscription reset
    [NOT_CONNECTED] Not connected
    [TORRENT_BLOCKED] Torrent restriction
    [BLACKLIST_ATTEMPT] User registration (from blacklist)
    *[OTHER] { $notification_type }
    }

language = { $language ->
    [ar] Arabic
    [az] Azerbaijani
    [be] Belarusian
    [bg] Bulgarian
    [cs] Czech
    [da] Danish
    [de] German
    [el] Greek
    [en] English
    [es] Spanish
    [fa] Persian
    [fi] Finnish
    [fr] French
    [he] Hebrew
    [hi] Hindi
    [hu] Hungarian
    [id] Indonesian
    [it] Italian
    [ja] Japanese
    [kk] Kazakh
    [ko] Korean
    [ms] Malay
    [nl] Dutch
    [no] Norwegian
    [pl] Polish
    [pt] Portuguese
    [ro] Romanian
    [ru] Russian
    [sr] Serbian
    [sv] Swedish
    [tg] Tajik
    [th] Thai
    [tr] Turkish
    [uk] Ukrainian
    [uz] Uzbek
    [vi] Vietnamese
    [zh] Chinese
    *[OTHER] { $language }
}