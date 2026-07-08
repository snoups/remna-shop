ntf-error =
    .unknown = ⚠️ <i>An error occurred.</i>
    .permission-denied = ⚠️ <i>You do not have sufficient permissions.</i>
    .log-not-found = ⚠️ <i>Log file not found.</i>
    .logs-disabled = ⚠️ <i>Logging to file is disabled.</i>

    .lost-context = ⚠️ <i>An error occurred. Restart the dialog with the /start command.</i>
    .lost-context-restart = ⚠️ <i>An error occurred. The dialog has been restarted.</i>

ntf-common =
    .trial-unavailable = ⚠️ <i>Trial subscription is temporarily unavailable.</i>
    .throttling = ⚠️ <i>You are sending too many requests. Please wait.</i>
    .double-click-confirm = ⚠️ <i>Press again to confirm the action.</i>
    .squads-empty = ⚠️ <i>Squads not found. Check for their presence in the panel.</i>

    .withdraw-points = ❌ <i>You do not have enough points to perform the exchange.</i>
    .internal-squads-empty = ❌ <i>Select at least one internal squad.</i>

    .invalid-value = ❌ <i>Invalid value.</i>
    .value-updated = ✅ <i>Parameter updated successfully.</i>
    .cooldown-active = ⏳ <i>Temporarily unavailable. Try again in { $available_at }.</i>

    .plan-not-found = ❌ <i>Plan not found or unavailable.</i>
    .connect-not-available =
    ⚠️ { $status ->
    [LIMITED]
    You have used up all available traffic. { $is_trial ->
    [0] { $traffic_strategy ->
        [NO_RESET] Renew your subscription to reset traffic and keep using the service!
        *[RESET] Traffic will be restored in { $reset_time }. You can also renew your subscription to reset traffic.
        }
    *[1] { $traffic_strategy ->
        [NO_RESET] Purchase a subscription to keep using the service!
        *[RESET] Traffic will be restored in { $reset_time }. You can also purchase a subscription to use the service without limits.
        }
    }
    [EXPIRED]
    { $is_trial ->
    [0] Your subscription has expired. Renew your subscription or purchase a new one.
    *[1] The free trial period has ended. Purchase a subscription to keep using the service.
    }
    *[OTHER] An error occurred while checking the status, or the subscription was disabled. Contact support.
    }

ntf-command =
    .paysupport = 💸 <b>To request a refund, contact the support service.</b>
    .rules = ⚠️ <b>Please review the <a href="{ $url }">Terms of Use</a> before using the service.</b>
    .help = 🆘 <b>Tap the button below to contact support.</b>

ntf-requirement =
    .channel-join-required = ❇️ Subscribe to our channel and get <b>free days, promotions and news</b>. After subscribing, tap "Confirm".
    .channel-join-required-left = ⚠️ You have unsubscribed from the channel. Subscribe to keep using the bot.
    .rules-accept-required = ⚠️ <b>Before using the service, review and accept the <a href="{ $url }">Terms of Use</a>.</b>
    .channel-join-error = ⚠️ We do not see your subscription to the channel. Check your subscription and try again.
    .trial-paused = ⚠️ The trial period is paused — you unsubscribed from the channel. Subscribe again to resume access.
    .trial-restored = ✅ The trial period has been resumed.

ntf-user =
    .not-found = <i>❌ User not found.</i>
    .transaction-not-found = ❌ <i>Transaction not found.</i>
    .transactions-empty = ❌ <i>The transaction list is empty.</i>
    .subscription-empty = ❌ <i>No active subscription found.</i>
    .subscription-deleted = ✅ <i>Subscription deleted successfully.</i>
    .plans-empty = ❌ <i>No plans available.</i>
    .devices-empty = ❌ <i>The device list is empty.</i>
    .allowed-plans-empty = ❌ <i>No plans available to grant access.</i>
    .referral-reset = ✅ <i>Referral link reset successfully.</i>
    .message-success = ✅ <i>Message sent successfully.</i>
    .message-failed = ❌ <i>Failed to send the message.</i>

    .sync-already = ✅ <i>Subscription data is identical.</i>
    .sync-missing-data = ⚠️ <i>Synchronization is not possible. Subscription data is missing in the panel and in the bot.</i>
    .sync-success = ✅ <i>Subscription synchronization completed.</i>

    .invalid-expire-time = ❌ <i>Cannot { $operation ->
    [ADD] extend
    *[SUB] shorten
    } the subscription period by the specified number of days.</i>

    .invalid-points = ❌ <i>Cannot { $operation ->
    [ADD] add
    *[SUB] deduct
    } the specified number of points.</i>

ntf-access =
    .maintenance = 🚧 <i>The bot is under maintenance. Try again later.</i>
    .registration-disabled = ❌ <i>Registration of new users is disabled.</i>
    .registration-invite-only = ❌ <i>Registration is available by invitation only.</i>
    .payments-disabled = 🚧 <i>Payments are temporarily unavailable! You will receive a notification once they are restored.</i>
    .payments-restored = ❇️ <i>Payments have been restored! You can now buy or renew a subscription. Thank you for waiting.</i>

ntf-plan =
    .not-file = ⚠️ <i>Send plans as a json file.</i>
    .import-failed = ❌ <i>Import failed.</i>
    .import-success = ✅ <i>Imported successfully.</i>
    .export-plans-not-selected = ❌ <i>Select at least one plan to export.</i>
    .export-failed = ❌ <i>Export failed.</i>
    .export-success = ✅ <i>Selected plans exported.</i>
    .trial-single-duration = ❌ <i>A trial plan can have only one duration.</i>
    .duration-already-exists = ❌ <i>This duration already exists.</i>
    .name-already-exists = ❌ <i>A plan with this name already exists.</i>
    .user-already-allowed = ❌ <i>The user identifier has already been added.</i>

    .updated = ✅ <i>Plan updated successfully.</i>
    .created = ✅ <i>Plan created successfully.</i>
    .deleted = ✅ <i>Plan deleted successfully.</i>

ntf-gateway =
    .not-configured = ❌ <i>The payment gateway is not configured.</i>
    .not-configurable = ❌ <i>The payment gateway has no settings.</i>
    .test-payment-created = ✅ <i><a href="{ $url }">Test payment</a> created successfully.</i>
    .test-payment-error = ❌ <i>Error creating the test payment.</i>
    .test-payment-confirmed = ✅ <i>Test payment processed successfully.</i>
    .field-reset = ✅ <i>Field value cleared.</i>
    .field-reset-deactivated = ✅ <i>Field value cleared. Gateway disabled: required settings are missing.</i>

ntf-subscription =
    .plans-unavailable = ❌ <i>There are no plans available at the moment.</i>
    .gateways-unavailable = ❌ <i>There are no payment systems available at the moment.</i>
    .renew-plan-unavailable = ❌ <i>The current plan is outdated and unavailable for renewal.</i>
    .payment-creation-failed = ❌ <i>Error creating the payment. Try again later.</i>

ntf-broadcast =
    .text-too-long = ❌ Maximum number of characters exceeded ({ $max_limit }).
    .list-empty = ❌ <i>The broadcast list is empty.</i>
    .plans-unavailable = ❌ <i>No plans available.</i>
    .audience-unavailable = ❌ <i>No users for the selected audience.</i>
    .content-empty = ❌ <i>The content is empty.</i>
    .content-saved = ✅ <i>Content saved successfully.</i>

    .not-cancelable = ❌ <i>The broadcast cannot be canceled.</i>
    .canceled = ✅ <i>Broadcast canceled successfully.</i>
    .deleting = ⚠️ <i>Deleting sent messages.</i>
    .already-deleted = ❌ <i>The broadcast has already been deleted or is being deleted.</i>

    .deleted-success =
        ℹ️ Deletion result for broadcast <code>{ $task_id }</code>.

        <blockquote>
        • <b>Total messages</b>: { $total_count }
        • <b>Deleted</b>: { $deleted_count }
        • <b>Failed to delete</b>: { $failed_count }
        </blockquote>

ntf-importer =
    .not-file = ⚠️ <i>Send the database as a file.</i>
    .db-failed = ❌ <i>Error exporting users from the database.</i>
    .users-empty = ❌ <i>The list of users in the database is empty.</i>

    .started = ✅ <i>Import started. Wait for completion...</i>
    .already-running = ⚠️ <i>Import is already running. Please wait.</i>

ntf-sync =
    .from-panel-started = ✅ <i>Panel → bot synchronization started. Wait for completion...</i>
    .from-bot-started = ✅ <i>Bot → panel synchronization started. Wait for completion...</i>
    .users-not-found = ❌ <i>No users found for synchronization.</i>
    .already-running = ⚠️ <i>Synchronization is already running. Please wait.</i>

ntf-menu-editor =
    .button-saved = ✅ <i>Button saved successfully.</i>
    .invalid-payload = ❌ <i>Invalid URL format.</i>

ntf-devices =
    .deleted = ✅ <i>Device deleted.</i>
    .all-deleted = ✅ <i>All devices deleted.</i>
    .reissued = ✅ <i>Subscription reissued successfully.</i>

ntf-backup =
    .assets-started = ⏳ <i>Creating assets backup...</i>
    .db-started = ⏳ <i>Creating database backup...</i>
    .error = ❌ <i>Error creating backup</i>

ntf-blacklist =
    .list-empty = ❌ <i>The blocked list is empty.</i>
    .no-ids-found = ❌ <i>No IDs found at the link.</i>
    .source-removed = ✅ <i>List removed.</i>
    .blocked-ids-empty = ❌ <i>The blocked ID list is empty.</i>
    .blocked-ids-cleared = ✅ <i>Cleared { $count } IDs.</i>

    .block-result =
    ℹ️ Blocking result.

    <blockquote>
    • <b>Total IDs</b>: { $total }
    • <b>Blocked users</b>: { $blocked_users }
    • <b>Blocked IDs</b>: { $blocked_ids }
    • <b>Already blocked</b>: { $already_blocked }
    </blockquote>

ntf-invite =
    .referral-reset = ✅ <i>Referral link updated.</i>

ntf-promocode =
    .not-found = ❌ <i>Promo code not found or invalid.</i>
    .not-available = ❌ <i>Promo code unavailable.</i>
    .expired = ❌ <i>The promo code has expired.</i>
    .already-activated = ❌ <i>You have already activated this promo code.</i>
    .activated = ✅ <i>Promo code activated successfully!</i>
    .activation-failed = ❌ <i>Failed to activate the promo code. Try again later.</i>
    .code-exists = ❌ <i>A promo code with this code already exists.</i>
    .created = ✅ <i>Promo code created.</i>
    .deleted = ✅ <i>Promo code deleted.</i>
    .fields-required = ❌ <i>Fill in the reward value.</i>
    .invalid-code = ❌ <i>The code may contain only Latin letters, digits, hyphen and underscore.</i>
    .plans-empty = ❌ <i>No plans available.</i>
    .updated = ✅ <i>Promo code updated.</i>

ntf-ad-link =
    .created = ✅ <i>Ad link created.</i>
    .updated = ✅ <i>Ad link updated.</i>
    .deleted = ✅ <i>Ad link deleted.</i>
