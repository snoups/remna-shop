event-error =
    .general =
    #ErrorEvent

    <b>🔅 Event: An error occurred!</b>

    { frg-build-info }

    { $telegram_id ->
    [0] { space }
    *[HAS]
    { hdr-user }
    { frg-user-info }
    }

    { hdr-error }
    <blockquote>
    { $error }
    </blockquote>

    .remnawave-version =
    #RemnawaveVersionWarningEvent

    <b>⚠️ Event: Possible incompatibility with Remnawave!</b>

    <blockquote>
    Panel version <b>{ $panel_version }</b> is higher than the tested version <b>{ $max_version }</b>. Some bot features may work incorrectly.
    </blockquote>

    { frg-build-info }

    .remnawave =
    #RemnawaveErrorEvent

    <b>🔅 Event: Error connecting to Remnawave!</b>

    <blockquote>
    Without an active connection, the bot cannot work correctly!
    </blockquote>

    { frg-build-info }

    { hdr-error }
    <blockquote>
    { $error }
    </blockquote>

    .webhook =
    #ErrorEvent

    <b>🔅 Event: A webhook error was recorded!</b>

    { hdr-error }
    <blockquote>
    { $error }
    </blockquote>

    .channel-check =
    #ChannelCheckErrorEvent

    <b>⚠️ Event: Channel/group subscription check error!</b>

    { hdr-user }
    { frg-user-info }

    <blockquote>
    • <b>Reason</b>: <code>{ $reason }</code>
    </blockquote>

    Make sure the bot is an admin of the channel/group with permission to view members.

    .notification =
    #NotificationErrorEvent

    <b>⚠️ Event: System notification delivery error!</b>

    <blockquote>
    • <b>Route</b>: { NUMBER($chat_id, useGrouping: 0) }{ $thread_id ->
        [0] { space }
        *[HAS] :{ NUMBER($thread_id, useGrouping: 0) }
    }
    • <b>Reason</b>: <code>{ $reason }</code>
    </blockquote>

    Check the notification route and make sure the bot is a member of the group with permission to send messages.


event-bot =
    .startup =
    #BotStartupEvent

    <b>🔅 Event: Bot started!</b>

    { frg-build-info }

    <b>🔓 Availability</b>:
    <blockquote>
    • <b>Mode</b>: { access-mode }
    • <b>Payments</b>: { $payments_allowed ->
    [0] disabled
    *[1] enabled
    }
    • <b>Registration</b>: { $registration_allowed ->
    [0] disabled
    *[1] enabled
    }
    </blockquote>

    .inline-mode-disabled =
    #BotInlineModeDisabledEvent

    <b>⚠️ Event: Inline mode is disabled in BotFather!</b>

    <blockquote>
    The bot is not configured for inline mode. Some bot features may work incorrectly.

    Enable Inline Mode in BotFather: <b>@BotFather → /mybots → Bot Settings → Inline Mode → Enable</b>
    </blockquote>

    .shutdown =
    #BotShutdownEvent

    <b>🔅 Event: Bot stopped!</b>

    { frg-build-info }

    <blockquote>
    • <b>Uptime</b>: { $uptime }
    </blockquote>

    .update =
    #BotUpdateEvent

    <b>🔅 Event: A Remnashop update was found!</b>

    <b>📑 Versions</b>:
    <blockquote>
    • <b>Current</b>: { $local_version }
    • <b>Latest</b>: { $remote_version }
    </blockquote>


event-user =
    .registered =
    #UserRegisteredEvent

    <b>🔅 Event: New user!</b>

    { hdr-user }
    { frg-user-info }

    { $referrer_user_id ->
    [0] { empty }
    *[HAS]
    <b>🤝 Referrer</b>:
    <blockquote>
    { $referrer_telegram_id ->
        [0] • <b>Email</b>: <code>{ $referrer_email }</code>
        *[HAS] • <b>ID</b>: <code>{ NUMBER($referrer_telegram_id, useGrouping: 0) }</code>
    }
    • <b>Name</b>: { $referrer_name } { $referrer_username ->
        [0] { empty }
        *[HAS] (<a href="tg://user?id={ $referrer_telegram_id }">@{ $referrer_username }</a>)
    }
    </blockquote>
    }

    { $ad_link_id ->
    [0] { empty }
    *[HAS]
    <b>🎯 Ad link</b>:
    <blockquote>
    • <b>Name</b>: { $ad_link_name }
    • <b>Code</b>: <code>{ $ad_link_code }</code>
    </blockquote>
    }

    .first-connected =
    #UserFirstConnectionEvent

    <b>🔅 Event: User's first connection!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-subscription }
    { frg-subscription-details }

    .device-added =
    #UserDeviceAddedEvent

    <b>🔅 Event: User added a new device!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-hwid }
    { frg-user-hwid }

    .device-deleted =
    #UserDeviceDeletedEvent

    <b>🔅 Event: User deleted a device!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-hwid }
    { frg-user-hwid }


event-blacklist =
    .registration-attempt =
    #BlacklistRegistrationAttemptEvent

    <b>🔅 Event: Registration attempt from the blacklist!</b>

    { hdr-user }
    { frg-user-info }


event-subscription =
    .trial =
    #SubscriptionTrialEvent

    <b>🔅 Event: Trial subscription obtained!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-plan }
    { frg-plan-snapshot }

    .new =
    #SubscriptionNewEvent

    <b>🔅 Event: Subscription purchased!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    { hdr-plan }
    { frg-plan-snapshot }

    .renew =
    #SubscriptionRenewEvent

    <b>🔅 Event: Subscription renewed!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    { hdr-plan }
    { frg-plan-snapshot }

    .change =
    #SubscriptionChangeEvent

    <b>🔅 Event: Subscription changed!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    { hdr-plan }
    { frg-plan-snapshot-comparison }

    .expiring =
    { $is_trial ->
    [0]
    <b>⚠️ Attention! Your subscription will end in { unit-day }.</b>

    Renew it in advance so you don't lose access to the service!
    *[1]
    <b>⚠️ Attention! Your free trial will end in { unit-day }.</b>

    Get a subscription so you don't lose access to the service!
    }

    .expired =
    <b>⛔ Attention! Access suspended — VPN is not working.</b>

    { $is_trial ->
    [0] Your subscription has expired, renew it to keep using the VPN!
    *[1] Your free trial period has ended. Get a subscription to keep using the service!
    }

    .expired-ago =
    <b>⛔ Attention! Access suspended — VPN is not working.</b>

    { $is_trial ->
    [0] Your subscription expired { unit-day } ago, renew it to keep using the service!
    *[1] Your free trial period ended { unit-day } ago. Get a subscription to keep using the service!
    }

    .limited =
    <b>⛔ Attention! Access suspended — VPN is not working.</b>

    Your traffic is used up. { $is_trial ->
    [0] { $traffic_strategy ->
        [NO_RESET] Renew your subscription to reset traffic and keep using the service!
        *[RESET] Traffic will be restored in { $reset_time }. You can also renew your subscription to reset traffic.
        }
    *[1] { $traffic_strategy ->
        [NO_RESET] Get a subscription to keep using the service!
        *[RESET] Traffic will be restored in { $reset_time }. You can also get a subscription to use the service without limits.
        }
    }

    .not-connected =
    <b>🔌 Couldn't connect?</b>

    If you ran into trouble setting up the VPN — we're ready to help! Message support and we'll sort it out together.

    .revoked =
    #SubscriptionRevokedEvent

    <b>🔅 Event: User reissued a subscription!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-subscription }
    { frg-subscription-details }


event-node =
    .connection-lost =
    #NodeConnectionLostEvent

    <b>🔅 Event: Connection to node lost!</b>

    { hdr-node }
    { frg-node-info }

    .connection-restored =
    #NodeConnectionRestoredEvent

    <b>🔅 Event: Connection to node restored!</b>

    { hdr-node }
    { frg-node-info }

    .traffic-reached =
    #NodeTrafficReachedEvent

    <b>🔅 Event: Node reached the traffic limit threshold!</b>

    { hdr-node }
    { frg-node-info }


event-torrent-blocker =
    .user-blocked =
    <b>⛔ Server access is temporarily restricted.</b>

    BitTorrent traffic was detected on node <b>{ $node_name }</b>.
    The restriction will remain in effect for another <b>{ $block_duration }</b>.

    If you need help setting up the connection, contact support.

    .report =
    #TorrentBlockedEvent

    <b>⚠️ Event: BitTorrent traffic detected!</b>

    { hdr-user }
    { frg-user-info }

    <blockquote>
    • <b>Node</b>: { $node_name }
    • <b>IP</b>: <code>{ $blocked_ip }</code>
    • <b>Block duration</b>: { $block_duration }
    • <b>Unblock</b>: { $will_unblock_at }
    • <b>Protocol</b>: <code>{ $protocol }</code>
    • <b>Source</b>: <code>{ $source }</code>
    • <b>Destination</b>: <code>{ $destination }</code>
    </blockquote>


event-referral =
    .attached =
    <b>🎉 You invited a friend!</b>

    <blockquote>
    User <b>{ $name }</b> joined via your invite link! To receive the reward, make sure they make a subscription purchase.
    </blockquote>

    .reward =
    <b>💰 You've been awarded a reward!</b>

    <blockquote>
    User <b>{ $name }</b> made a payment. You received { $reward_type ->
    [POINTS] <b>{ $value } { $value ->
        [one] point
        *[other] points
        }</b>

    <i>To use points, go to the "Invite" section in the bot to learn about available rewards and how to use them.</i>
    [EXTRA_DAYS] <b>{ $value } extra { $value ->
        [one] day
        *[other] days
        }</b> added to your subscription!
    *[OTHER] <b>{ $value } { $reward_type }</b>
    }
    </blockquote>

    .reward-failed =
    <b>❌ Couldn't grant the reward!</b>

    <blockquote>
    User <b>{ $name }</b> made a payment, but we couldn't award you the reward because <b>you don't have a purchased subscription</b> to add { $value } { $reward_type ->
    [POINTS] { $value ->
        [one] point
        *[other] points
        }
    [EXTRA_DAYS] extra { $value ->
        [one] day
        *[other] days
        }
    *[OTHER] { $reward_type }
    } to.

    <i>Buy a subscription to receive bonuses for invited friends!</i>
    </blockquote>

event-promocode =
    .activated =
    #PromocodeActivatedEvent

    <b>🔅 Event: Promo code activated!</b>

    { hdr-user }
    { frg-user-info }

    <b>🎟 Promo code</b>:
    <blockquote>
    • <b>Code</b>: <code>{ $promocode_code }</code>
    • <b>Type</b>: { promocode-type }
    • <b>Reward</b>: { frg-promocode-reward }
    </blockquote>

event-payment =
    .refunded =
    #PaymentRefundedEvent

    <b>⚠️ Event: Payment refunded!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    Manual review required — the user's subscription may have remained active.

    .referral-failed =
    <b>⚠️ Failed to award the referral reward</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    The purchase completed successfully, but an error occurred while awarding the referral reward. Manual review required.

    .purchase-failed =
    <b>⚠️ Event: Payment processing error!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    Payment received, but the subscription could not be granted. The transaction is marked as FAILED. Manual review required.

event-remnashop-welcome =
    <b>💎 Remnashop v{ $version }</b>

    The project is created and maintained by just one <strike>developer</strike> electrician. Since the bot is completely FREE and open source, it exists only thanks to your support.

    ⭐ <i>Star it on <a href="{ $repository }">GitHub</a> and join our <a href="https://t.me/@remna_shop">community</a>.</i>

    🎁 <i>There is also a <a href="https://boosty.to/snoups/purchase/3778398?ssource=DIRECT&amp;share=subscription_link">private chat</a> for donors.</i>