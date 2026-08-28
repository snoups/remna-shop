# Menu
msg-main-menu =
    { hdr-user-profile }
    { frg-user }

    { hdr-subscription }
    { $status ->
    [ACTIVE]
    { frg-subscription }
    [EXPIRED]
    <blockquote>
    • Срок действия истек.
    
    <i>{ $is_trial ->
    [0] Ваша подписка истекла. Продлите ее, чтобы продолжить пользоваться сервисом!
    *[1] Ваш бесплатный пробный период закончился. Оформите подписку, чтобы продолжить пользоваться сервисом!
    }</i>
    </blockquote>
    [LIMITED]
    <blockquote>
    • Ваш трафик израсходован.

    <i>{ $is_trial ->
    [0] { $traffic_strategy ->
        [NO_RESET] Продлите подписку, чтобы сбросить трафик и продолжить пользоваться сервисом!
        *[RESET] Трафик будет восстановлен через { $reset_time }. Вы также можете продлить подписку, чтобы сбросить трафик.
        }
    *[1] { $traffic_strategy ->
        [NO_RESET] Оформите подписку, чтобы продолжить пользоваться сервисом!
        *[RESET] Трафик будет восстановлен через { $reset_time }. Вы также можете оформить подписку, чтобы пользоваться сервисом без ограничений.
        }
    }</i>
    </blockquote>
    [DISABLED]
    <blockquote>
    • Ваша подписка отключена.

    <i>Свяжитесь с поддержкой для выяснения причины!</i>
    </blockquote>
    *[NONE]
    <blockquote>
    • У вас нет оформленной подписки.

    <i>{ $trial_available ->
    [1] 🎁 Для вас доступен бесплатный пробник — нажмите кнопку ниже, чтобы его получить.
    *[0] ↘️ Для покупки доступа перейдите в меню «Подписка».
    }</i>
    </blockquote>
    }

msg-menu-devices =
    <b>📱 Управление устройствами</b>

    Подключено: <b>{ $current_count } / { $max_count -> 
    [0] { unlimited }
    *[LIMIT] { $max_count }
    }</b>

    { $has_devices ->
    [0] { empty }
    *[HAS] { $device_single_enabled ->
        [0] Для отвязки устройства обратитесь в техподдержку.
        *[OTHER] Нажмите на устройство чтобы удалить его.
        }
    }{ $max_count ->
    [0] { space }
    *[LIMIT] Если не хватает лимита устройств — измените подписку.
    }

msg-menu-devices-confirm-reissue =
    🔄 <b>Перевыпуск подписки</b>

    ⚠️ После сброса старая ссылка <b>перестанет работать</b> и все устройства придется заново переподключать.

    Вам потребуется:
    • Удалить старую подписку из приложения
    • Добавить новую ссылку из раздела «{ btn-menu.connect }»

    Вы уверены, что хотите сбросить ссылку?

msg-menu-devices-confirm-delete =
    🗑 <b>Подтвердите удаление устройства</b>

    <b>{ $device_model }</b>
    <blockquote>
    • <b>Платформа</b>: { $platform_icon } { $platform }
    • <b>Добавлено</b>: { $created_at }
    </blockquote>

msg-menu-devices-confirm-delete-all =
    🗑 <b>Подтвердите удаление всех устройств</b>

msg-menu-invite =
    <b>👥 Пригласить друзей</b>
    
    Делитесь вашей уникальной ссылкой и получайте вознаграждение в виде { $reward_type ->
        [POINTS] <b>баллов, которые можно обменять на подписку или реальные деньги</b>
        [EXTRA_DAYS] <b>бесплатных дней к вашей подписке</b>
        *[OTHER] { $reward_type }
    }!

    <b>📊 Статистика</b>:
    <blockquote>
    👥 Всего приглашенных: { $referrals }
    💳 Платежей по вашей ссылке: { $payments }
    { $reward_type -> 
    [POINTS] 💎 Ваши баллы: { $points }
    *[EXTRA_DAYS] { empty }
    }
    </blockquote>

msg-menu-invite-about =
    <b>🎁 Подробнее о вознаграждении</b>

    <b>✨ Как получить награду</b>:
    <blockquote>
    { $accrual_strategy ->
    [ON_FIRST_PAYMENT] Награда начисляется за первую покупку подписки приглашенным пользователем.
    [ON_EACH_PAYMENT] Награда начисляется за каждую покупку или продление подписки приглашенным пользователем.
    *[OTHER] { $accrual_strategy }
    }
    </blockquote>

    <b>💎 Что вы получаете</b>:
    <blockquote>
    { $max_level -> 
    [1] За приглашенных друзей: { $reward_level_1 }
    *[MORE]
    { $identical_reward ->
    [0]
    1️⃣ За ваших друзей: { $reward_level_1 }
    2️⃣ За приглашенных вашими друзьями: { $reward_level_2 }
    *[1]
    За ваших друзей и приглашенных вашими друзьями: { $reward_level_1 }
    }
    }
    
    { $reward_strategy_type ->
    [AMOUNT] { $reward_type ->
        [POINTS] { space }
        [EXTRA_DAYS] <i>(Все дополнительные дни начисляются к вашей текущей подписке)</i>
        *[OTHER] { $reward_type }
    }
    [PERCENT] { $reward_type ->
        [POINTS] <i>(Процент баллов от стоимости их приобретенной подписки)</i>
        [EXTRA_DAYS] <i>(Процент доп. дней от их приобретенной подписки)</i>
        *[OTHER] { $reward_type }
    }
    *[OTHER] { $reward_strategy_type }
    }
    </blockquote>

msg-invite-reward = { $value }{ $reward_strategy_type ->
    [AMOUNT] { $reward_type ->
        [POINTS] { space }{ $value -> 
            [one] балл
            [few] балла
            *[more] баллов 
            }
        [EXTRA_DAYS] { space }доп. { $value -> 
            [one] день
            [few] дня
            *[more] дней
            }
        *[OTHER] { $reward_type }
    }
    [PERCENT] % { $reward_type ->
        [POINTS] баллов
        [EXTRA_DAYS] доп. дней
        *[OTHER] { $reward_type }
    }
    *[OTHER] { $reward_strategy_type }
    }


# Dashboard
msg-dashboard-main = <b>🛠 Панель управления</b>
msg-users-main = <b>👥 Пользователи</b>
msg-broadcast-main = <b>📢 Рассылка</b>
msg-statistics-main = <b>📊 Статистика</b>
    
msg-statistics-users =
    <b>👥 Статистика по пользователям</b>

    <blockquote>
    • <b>Всего</b>: { $total_users }
    • <b>Новые за день</b>: { $new_users_daily }
    • <b>Новые за неделю</b>: { $new_users_weekly }
    • <b>Новые за месяц</b>: { $new_users_monthly }

    • <b>С подпиской</b>: { $users_with_subscription }
    • <b>Без подписки</b>: { $users_without_subscription }
    • <b>С пробным периодом</b>: { $users_with_trial }
    </blockquote>

    <blockquote>
    • <b>Заблокированные</b>: { $blocked_users }
    • <b>Заблокировали бота</b>: { $bot_blocked_users }

    • <b>Конверсия пользователей → покупка</b>: { $user_conversion }%
    • <b>Конверсия пробников → подписка</b>: { $trial_conversion }%
    </blockquote>

msg-statistics-subscriptions =
    { $plan_name ->
    [0] <b>💳 Статистика по подпискам</b>
    *[HAS] <b>📦 Статистика плана «{ $plan_name }»</b>
    }

    <blockquote>
    • <b>Всего</b>: { $total }
    • <b>Активные</b>: { $total_active }
    • <b>Отключенные</b>: { $total_disabled }
    • <b>Ограниченные</b>: { $total_limited }
    • <b>Истекшие</b>: { $total_expired }
    • <b>Истекающие (7 дней)</b>: { $expiring_soon }
    { $plan_name ->
    [0] • <b>Пробные</b>: { $active_trial }
    *[HAS] • <b>Популярная длительность</b>: { $popular_duration }
    }
    </blockquote>

    { $plan_name ->
    [0] <blockquote>
    • <b>С безлимитом</b>: { $total_unlimited }
    • <b>С лимитом трафика</b>: { $total_traffic }  
    • <b>С лимитом устройств</b>: { $total_devices }
    </blockquote>
    *[HAS] <b>Общий доход</b>:
    <blockquote>
    { $all_income }
    </blockquote>
    }
    
msg-statistics-subscriptions-plan-income = { $income }{ $currency }
    
msg-statistics-transactions =
    { $gateway_type ->
    [0] <b>🧾 Общая статистика по транзакциям</b>
    *[HAS] <b>🧾 Статистика { gateway-type }</b>
    }

    <blockquote>
    • <b>Всего транзакций</b>: { $total_transactions }
    • <b>Завершенных транзакций</b>: { $completed_transactions }
    • <b>Бесплатных транзакций</b>: { $free_transactions }
    { $gateway_type ->
    [0] { $popular_gateway ->
        [0] { empty }
        *[HAS] • <b>Популярная платежная система</b>: { $popular_gateway }
        }
    *[HAS] { empty }
    }
    </blockquote>

    { $gateway_type ->
    [0] { empty }
    *[HAS] <blockquote>
    • <b>Общий доход</b>: { $total_income }{ $currency }
    • <b>Доход за день</b>: { $daily_income }{ $currency }
    • <b>Доход за неделю</b>: { $weekly_income }{ $currency }
    • <b>Доход за месяц</b>: { $monthly_income }{ $currency }
    • <b>Доход за прошлый месяц</b>: { $last_month_income }{ $currency }
    • <b>Средний чек</b>: { $average_check }{ $currency }
    • <b>Сумма скидок</b>: { $total_discounts }{ $currency }
    </blockquote>
    }

msg-statistics-promocodes =
    <b>🎁 Статистика по промокодам</b>

    <blockquote>
    • <b>Всего промокодов</b>: { $total_promocodes }
    • <b>Активных</b>: { $active_promocodes }
    • <b>Всего активаций</b>: { $total_activations }
    </blockquote>

    <blockquote>
    • <b>Активаций за день</b>: { $activations_today }
    • <b>Активаций за неделю</b>: { $activations_week }
    • <b>Активаций за месяц</b>: { $activations_month }
    </blockquote>

    <blockquote>
    • <b>Выдано дней</b>: { $issued_days }
    • <b>Выдано трафика (ГБ)</b>: { $issued_traffic }
    • <b>Выдано устройств</b>: { $issued_devices }
    • <b>Выдано подписок</b>: { $issued_subscriptions }
    • <b>Выдано личных скидок</b>: { $issued_personal_discounts }
    • <b>Выдано одноразовых скидок</b>: { $issued_purchase_discounts }
    </blockquote>

msg-statistics-promocode-detail =
    <b>🎁 Промокод</b> <code>{ $code }</code>

    <blockquote>
    • <b>Тип</b>: { promocode-type }
    • <b>Награда</b>: { $reward }
    • <b>Статус</b>: { $is_active ->
        [1] 🟢 Включен
        *[0] 🔴 Выключен
        }
    • <b>Повторная активация</b>: { $is_reusable ->
        [1] Разрешена
        *[0] Запрещена
        }
    </blockquote>

    <blockquote>
    • <b>Создан</b>: { $created_at }
    • <b>Действует до</b>: { $expires_at }
    • <b>Лимит активаций</b>: { $max_activations }
    • <b>Осталось активаций</b>: { $remaining }
    </blockquote>

    <blockquote>
    • <b>Всего активаций</b>: { $total_activations }
    • <b>За день</b>: { $activations_today }
    • <b>За неделю</b>: { $activations_week }
    • <b>За месяц</b>: { $activations_month }
    </blockquote>

msg-statistics-referrals =
    <b>👪 Статистика по рефералам</b>

    <blockquote>
    • <b>Всего рефералов</b>: { $total_referrals }
    • <b>Уровень 1</b>: { $level_1_count }
    • <b>Уровень 2</b>: { $level_2_count }
    • <b>Уникальных реферреров</b>: { $unique_referrers }
    { $top_referrer_id ->
        [0] { empty }
        *[HAS] • <b>Топ реферрер</b>: { $top_referrer_telegram_id ->
            [0] <code>{ $top_referrer_email }</code>
            *[HAS] { $top_referrer_username ->
                [0] { NUMBER($top_referrer_telegram_id, useGrouping: 0) }
                *[HAS] <a href="tg://user?id={ $top_referrer_telegram_id }">@{ $top_referrer_username }</a>
            }
        } ({ $top_referrer_referrals_count } приглашенных)
    }
    </blockquote>

    <blockquote>
    • <b>Выдано наград</b>: { $total_rewards_issued }
    • <b>Выдано баллов</b>: { $total_points_issued }
    • <b>Выдано дней</b>: { $total_days_issued }
    </blockquote>


# Access
msg-access-main =
    <b>🔓 Режим доступа</b>
    
    <blockquote>
    • <b>Режим</b>: { access-mode }
    • <b>Платежи</b>: { $payments_allowed ->
    [0] запрещены
    *[1] разрешены
    }.
    • <b>Регистрация</b>: { $registration_allowed ->
    [0] запрещена
    *[1] разрешена
    }.
    </blockquote>

msg-access-conditions =
    <b>⚙️ Условия доступа</b>

msg-access-rules =
    <b>✳️ Изменить ссылку на правила</b>

    { $rules_url ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $rules_url }
    </blockquote>
    }

    Введите ссылку (в формате https://telegram.org/tos).

msg-access-channel =
    <b>❇️ Изменить ссылку на канал/группу</b>

    { $channel_url ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $channel_url } { $channel_id -> 
        [0] { empty } 
        *[HAS] (ID: { $channel_id }) 
        }
    </blockquote>
    }
    
    Если ваша группа не имеет @username, отправьте ID группы и ссылку-приглашение отдельными сообщениями.
    
    Если у вас публичный канал/группа, введите только @username.


# Broadcast
msg-broadcast-list = <b>📄 Список рассылок</b>
msg-broadcast-plan-select = <b>📦 Выберите план для рассылки</b>
msg-broadcast-send = <b>📢 Отправить рассылку ({ audience-type })</b>

    { $audience_count } { $audience_count ->
    [one] пользователю
    [few] пользователям
    *[more] пользователей
    } будет отправлена рассылка

msg-broadcast-content =
    <b>✉️ Содержимое рассылки</b>

    Отправьте сообщение (поддерживается HTML). Можно прикрепить фото, видео или файл. Лимит: до 4096 символов без медиа, до 1024 символов с медиа.

msg-broadcast-buttons = <b>✳️ Кнопки рассылки</b>

msg-broadcast-view =
    <b>📢 Рассылка</b>

    <blockquote>
    • <b>ID</b>: <code>{ $broadcast_id }</code>
    • <b>Статус</b>: { broadcast-status }
    • <b>Аудитория</b>: { audience-type }
    • <b>Создано</b>: { $created_at }
    </blockquote>

    <blockquote>
    • <b>Всего сообщений</b>: { $total_count }
    • <b>Успешных</b>: { $success_count }
    • <b>Неудачных</b>: { $failed_count }
    </blockquote>


# Users
msg-users-recent-registered = <b>🆕 Последние зарегистрированные</b>
msg-users-recent-activity = <b>📝 Последние взаимодействующие</b>
msg-user-transactions = <b>🧾 Транзакции пользователя</b>
msg-user-devices = <b>📱 Устройства пользователя ({ $current_count } / { $max_count })</b>
msg-user-give-access = <b>🔑 Предоставить доступ к плану</b>

msg-users-search =
    <b>🔍 Поиск пользователя</b>

    Введите ID или Email пользователя, часть имени или перешлите любое его сообщение.

msg-users-search-results =
    <b>🔍 Поиск пользователя</b>

    Найдено <b>{ $count }</b> { $count ->
    [one] пользователь
    [few] пользователя
    *[more] пользователей
    }, { $count ->
    [one] соответствующий
    *[more] соответствующих
    } запросу

msg-user-main = 
    <b>📝 Информация о пользователе</b>

    { hdr-user-profile }
    { frg-user-details }

    <b>💸 Скидка</b>:
    <blockquote>
    • <b>Персональная</b>: { $personal_discount }%
    • <b>На следующую покупку</b>: { $purchase_discount }%
    </blockquote>
    
    { hdr-subscription }
    { $status ->
    [ACTIVE]
    { frg-subscription-user-editor }
    [EXPIRED]
    <blockquote>
    • Срок действия истек.
    </blockquote>
    [LIMITED]
    <blockquote>
    • Превышен лимит трафика.
    </blockquote>
    [DISABLED]
    <blockquote>
    • Подписка отключена.
    </blockquote>
    *[NONE]
    <blockquote>
    • Нет текущей подписки.
    </blockquote>
    }

msg-user-statistics =
    <b>📊 Статистика пользователя</b>

    <blockquote>
    • <b>Дата регистрации</b>: { $registered_at }
    • <b>Последний платеж</b>: { $last_payment_at ->
        [0] { unknown }
        *[HAS] { $last_payment_at }
    }
    </blockquote>

    { $payment_amounts ->
    [0] { space }
    *[HAS] <blockquote>
    { $payment_amounts }
    </blockquote>
    }

    <blockquote>
    • <b>Приглашен</b>: { $referrer_telegram_id ->
        [0] { $referrer_email ->
            [0] { unknown }
            *[HAS] <code>{ $referrer_email }</code>
        }
        *[HAS] { $referrer_username ->
            [0] { NUMBER($referrer_telegram_id, useGrouping: 0) }
            *[HAS] <a href="tg://user?id={ $referrer_telegram_id }">@{ $referrer_username }</a>
        }
    }
    • <b>Приглашенных (ур. 1)</b>: { $referrals_level_1 }
    • <b>Приглашенных (ур. 2)</b>: { $referrals_level_2 }
    • <b>Получено поинтов</b>: { $reward_points }
    • <b>Получено дней</b>: { $reward_days }
    </blockquote>

msg-user-statistics-payment-amount = • <b>Оплачено ({ $currency })</b>: { $amount }

msg-user-referrals = <b>👪 Рефералы пользователя</b>

msg-user-sync = 
    <b>🌀 Синхронизировать пользователя</b>

    <b>🛍 Remnashop</b>: { $bot_version }
    <blockquote>
    { $has_bot_subscription -> 
    [0] Данные отсутствуют
    *[HAS]{ $bot_subscription }
    }
    </blockquote>

    <b>🌊 Remnawave</b>: { $remna_version }
    <blockquote>
    { $has_remna_subscription -> 
    [0] Данные отсутствуют
    *[HAS] { $remna_subscription }
    }
    </blockquote>

    Выберите источник данных для синхронизации.

msg-user-sync-version = { $version ->
    [NEWER] (новее)
    [OLDER] (старее)
    *[UNKNOWN] { empty }
    }

msg-user-sync-subscription =
    • <b>ID</b>: <code>{ $id }</code>
    • Статус: { $status -> 
    [ACTIVE] Активна
    [DISABLED] Отключена
    [LIMITED] Исчерпан трафик
    [EXPIRED] Истекла
    [DELETED] Удалена
    *[OTHER] { $status }
    }
    • Ссылка: <a href="{ $url }">*********</a>

    • Лимит трафика: { $traffic_limit }
    • Лимит устройств: { $device_limit }
    • Осталось: { $expire_time }

    • Внутренние сквады: { $internal_squads ->
    [0] { unknown }
    *[HAS] { $internal_squads }
    }
    • Внешний сквад: { $external_squad ->
    [0] { unknown }
    *[HAS] { $external_squad }
    }
    • Сброс трафика: { $traffic_limit_strategy -> 
    [NO_RESET] При оплате
    [DAY] Каждый день
    [WEEK] Каждую неделю
    [MONTH] Каждый месяц
    [MONTH_ROLLING] Каждый месяц (по дате создания)
    *[OTHER] { $traffic_limit_strategy }
    }
    • Тег: { $tag -> 
    [0] { unknown }
    *[HAS] { $tag }
    }

msg-user-sync-waiting =
    <b>🌀 Синхронизация пользователя</b>

    Пожалуйста, подождите... Идет процесс синхронизации данных пользователя. Вы автоматически вернетесь к редактору пользователя по завершении.

msg-user-give-subscription =
    <b>🎁 Выдать подписку</b>

    Выберите план, который хотите выдать пользователю.

msg-user-give-subscription-duration =
    <b>⏳ Выберите длительность</b>

    Выберите длительность выдаваемой подписки.

msg-user-discount =
    <b>💸 Изменить скидку</b>

    Выберите тип скидки для изменения.

msg-user-discount-personal =
    <b>👤 Персональная скидка</b>

    Выберите по кнопке или введите свой вариант.

msg-user-discount-purchase =
    <b>🎟 Скидка на следующую покупку</b>

    Выберите по кнопке или введите свой вариант.
    Скидка будет применена один раз и сброшена после любого платежа.

msg-user-points =
    <b>💎 Изменить баллы реферальной системы</b>

    <b>Текущее кол-во баллов: { $current_points }</b>

    Выберите по кнопке или введите свой вариант, чтобы добавить или отнять.

msg-user-subscription-traffic-limit =
    <b>🌐 Изменить лимит трафика</b>

    Выберите по кнопке или введите свой вариант (в ГБ), чтобы изменить лимит трафика.

msg-user-subscription-device-limit =
    <b>📱 Изменить лимит устройств</b>

    Выберите по кнопке или введите свой вариант, чтобы изменить лимит устройств.

msg-user-subscription-expire-time =
    <b>⏳ Изменить срок действия</b>

    <b>Закончится через: { $expire_time }</b>

    Выберите по кнопке или введите свой вариант (в днях), чтобы добавить или отнять.

msg-user-subscription-squads =
    <b>🔗 Изменить список сквадов</b>

    { $internal_squads ->
    [0] { empty }
    *[HAS] <b>⏺️ Внутренние</b>: { $internal_squads }
    }

    { $external_squad ->
    [0] { empty }
    *[HAS] <b>⏹️ Внешний</b>: { $external_squad }
    }

msg-user-subscription-internal-squads =
    <b>⏺️ Изменить список внутренних сквадов</b>

    Выберите, какие внутренние группы будут присвоены этому пользователю.

msg-user-subscription-external-squads =
    <b>⏹️ Изменить внешний сквад</b>

    Выберите, какая внешняя группа будет присвоена этому пользователю.

msg-user-subscription-info =
    <b>💳 Информация о текущей подписке</b>
    
    { hdr-subscription }
    { frg-subscription-details }

    <blockquote>
    • <b>Внутренние сквады</b>: { $internal_squads ->
    [0] { unknown }
    *[HAS] { $internal_squads }
    }
    • <b>Внешний сквад</b>: { $external_squad ->
    [0] { unknown }
    *[HAS] { $external_squad }
    }
    • <b>Первое подключение</b>: { $first_connected_at -> 
    [0] { unknown }
    *[HAS] { $first_connected_at }
    }
    • <b>Последнее подключение</b>: { $last_connected_at ->
    [0] { unknown }
    *[HAS] { $last_connected_at } ({ $node_name })
    } 
    </blockquote>

    { hdr-plan }
    { frg-plan-snapshot }

msg-user-transaction-info =
    <b>🧾 Информация о транзакции</b>

    { hdr-payment }
    <blockquote>
    • <b>ID</b>: <code>{ $payment_id }</code>
    • <b>Пользователь</b>: { $user_name } ({ $user_telegram_id ->
        [0] <code>{ $user_email }</code>
        *[HAS] <code>{ NUMBER($user_telegram_id, useGrouping: 0) }</code>
    })
    • <b>Тип</b>: { purchase-type }
    • <b>Статус</b>: { transaction-status }
    • <b>Способ оплаты</b>: { gateway-type }
    • <b>Сумма</b>: { frg-payment-amount }
    • <b>Создано</b>: { $created_at }
    </blockquote>

    { $is_test -> 
    [1] ⚠️ Тестовая транзакция
    *[0]
    { hdr-plan }
    { frg-plan-snapshot }
    }
    
msg-user-role = 
    <b>👮‍♂️ Изменить роль</b>
    
    Выберите новую роль для пользователя.

msg-users-blacklist =
    <b>🚫 Черный список</b>

msg-users-blacklist-list =
    <b>📋 Заблокированные пользователи</b>

    Заблокировано: <b>{ $count_blocked }</b> / <b>{ $count_users }</b> ({ $percent }%).

msg-users-blacklist-block =
    <b>⛔ Заблокировать по ID</b>

    Поддерживаемые форматы
    <blockquote>
    • <b>Текст</b>: введите один или список ID
    • <b>Ссылка</b>: отправьте URL со списком ID
    • <b>Файл</b>: прикрепите .txt файл со списком ID
    </blockquote>

    Для списков: каждый ID должен быть с новой строки.

    Блокировка действует даже если пользователь ни разу не использовал бота.

msg-users-blacklist-sources =
    <b>🔗 Автообновляемые черные списки</b>

    Нажмите на список, чтобы удалить его.
    Синхронизация запускается автоматически каждые 6 часов.

    Чтобы добавить новый список — отправьте прямую ссылку на текстовый файл с Telegram ID.

msg-user-message =
    <b>📩 Отправить сообщение пользователю</b>

    Отправьте любое сообщение: текст, изображение или все вместе (поддерживается HTML).
    

# RemnaWave
msg-remnawave-main =
    <b>🌊 RemnaWave v{ $version }</b>
    
    <b>🖥️ Система</b>:
    <blockquote>
    • <b>ЦПУ</b>: { $cpu_cores } { $cpu_cores ->
    [one] ядро
    [few] ядра
    *[more] ядер
    }
    • <b>ОЗУ</b>: { $ram_used } / { $ram_total } ({ $ram_used_percent }%)
    • <b>Аптайм</b>: { $uptime }
    </blockquote>

msg-remnawave-users =
    <b>👥 Пользователи</b>

    <b>📊 Статистика</b>:
    <blockquote>
    • <b>Всего</b>: { $users_total }
    • <b>Активные</b>: { $users_active }
    • <b>Отключенные</b>: { $users_disabled }
    • <b>Ограниченные</b>: { $users_limited }
    • <b>Истекшие</b>: { $users_expired }
    </blockquote>

    <b>🟢 Онлайн</b>:
    <blockquote>
    • <b>За день</b>: { $online_last_day }
    • <b>За неделю</b>: { $online_last_week }
    • <b>Никогда не заходили</b>: { $online_never }
    • <b>Сейчас онлайн</b>: { $online_now }
    </blockquote>

msg-remnawave-host-details =
    <b>{ $remark } ({ $is_disabled ->
    [1] выключен
    *[0] включен
    })</b>:
    <blockquote>
    • <b>Адрес</b>: <code>{ $address }:{ $port }</code>
    { $inbound_uuid ->
    [0] { empty }
    *[HAS] • <b>Инбаунд</b>: <code>{ $inbound_uuid }</code>
    }
    </blockquote>

msg-remnawave-node-details =
    <b>{ $country } { $name } ({ $is_connected ->
    [1] подключено
    *[0] отключено
    })</b>:
    <blockquote>
    • <b>Адрес</b>: <code>{ $address }{ $port -> 
    [0] { empty }
    *[HAS]:{ $port }
    }</code>
    • <b>Аптайм (xray)</b>: { $xray_uptime }
    • <b>Пользователей онлайн</b>: { $users_online }
    • <b>Трафик</b>: { $traffic_used } / { $traffic_limit }
    </blockquote>

msg-remnawave-inbound-details =
    <b>🔗 { $tag }</b>
    <blockquote>
    • <b>ID</b>: <code>{ $inbound_id }</code>
    • <b>Протокол</b>: { $type } { $network -> 
    [0] { space }
    *[HAS] ({ $network })
    }
    { $port ->
    [0] { empty }
    *[HAS] • <b>Порт</b>: { $port }
    }
    { $security ->
    [0] { empty }
    *[HAS] • <b>Безопасность</b>: { $security } 
    }
    </blockquote>

msg-remnawave-hosts =
    <b>🌐 Хосты</b>

    { $is_empty ->
    [1] <i>Нет хостов</i>
    *[0] { $host }
    }

msg-remnawave-nodes =
    <b>🖥️ Ноды</b>

    { $is_empty ->
    [1] <i>Нет нод</i>
    *[0] { $node }
    }

msg-remnawave-inbounds =
    <b>🔌 Инбаунды</b>

    { $is_empty ->
    [1] <i>Нет инбаундов</i>
    *[0] { $inbound }
    }


# RemnaShop
msg-remnashop-main = <b>🛍 RemnaShop { $version ->
[0] { space }
*[HAS] { $version }
}</b>

msg-remnashop-transactions = <b>🧾 Последние транзакции</b>


# Backup
msg-backup-main =
    <b>💾 Авто-бэкап базы данных</b>

    <blockquote>
    • <b>Статус</b>: { $enabled ->
        [1] 🟢 Включен
        *[0] 🔴 Выключен
    }
    • <b>Отправка в чат</b>: { $send_to_chat ->
        [1] ✅ Включена
        *[0] ❌ Выключена
    }
    • <b>Интервал</b>:  { $interval_hours ->
    [one] каждый
    *[OTHER] каждые
    } { $interval_hours } ч.
    • <b>Кол-во файлов</b>: { $max_files }
    </blockquote>

msg-backup-set-interval =
    <b>🕐 Интервал бэкапа</b>

    Текущее значение: <b>{ $interval_hours } ч.</b>

    Введите интервал бэкапа в часах (от 1 до 720).

msg-backup-set-max-files =
    <b>📁 Количество файлов</b>

    Текущее значение: <b>{ $max_files }</b>

    Введите сколько файлов бэкапа хранить (от 1 до 30). Старые файлы будут удаляться автоматически.

msg-extra-main = <b>⚙️ Дополнительные настройки</b>

msg-extra-device-single =
    ⚙️ <b>Удаление одного устройства</b>

    Позволяет пользователю удалить конкретное устройство из списка.

    <blockquote>
    <b>Статус:</b> { $enabled -> 
        [1] 🟢 Включено
        *[0] 🔴 Выключено
    }
    <b>Кулдаун:</b> { $cooldown -> 
        [0] { unknown }
        *[OTHER] { $cooldown }ч
    }
    </blockquote>

    Введите число для изменения кулдауна (в часах. 0 — без ограничений).

msg-extra-device-all =
    ⚙️ <b>Удаление всех устройств</b>

    Позволяет пользователям удалить все устройства одним нажатием.

    <blockquote>
    <b>Статус:</b> { $enabled -> 
        [1] ✅ Включено
        *[0] ❌ Выключено
    }
    <b>Кулдаун:</b> { $cooldown -> 
        [0] { unknown }
        *[OTHER] { $cooldown }ч
    }
    </blockquote>

    Введите число для изменения кулдауна (в часах. 0 — без ограничений).

msg-extra-link-reset =
    ⚙️ <b>Перевыпуск подписки</b>

    Позволяет перевыпустить ссылку подключения (инвалидирует старую).

    <blockquote>
    <b>Статус:</b> { $enabled -> 
        [1] ✅ Включено
        *[0] ❌ Выключено
    }
    <b>Кулдаун:</b> { $cooldown -> 
        [0] { unknown }
        *[OTHER] { $cooldown }ч
    }
    </blockquote>

    Введите число для изменения кулдауна (в часах. 0 — без ограничений).

msg-extra-referral-reset =
    ⚙️ <b>Сброс реферальной ссылки</b>

    Позволяет пользователям изменить свою реферальную ссылку.

    <blockquote>
    <b>Статус:</b> { $enabled -> 
        [1] ✅ Включено
        *[0] ❌ Выключено
    }
    <b>Кулдаун:</b> { $cooldown -> 
        [0] { unknown }
        *[OTHER] { $cooldown }ч
    }
    </blockquote>

    Введите число для изменения кулдауна (в часах. 0 — без ограничений).

msg-extra-trial-channel-guard =
    ⚙️ <b>Авто отключение пробника при отписке от канала</b>

    Если пользователь отписывается от обязательного канала/группы во время пробного периода, его подписка автоматически приостанавливается. После повторной подписки доступ восстанавливается, если триал еще не истек.

    <blockquote>
    <b>Статус:</b> { $enabled ->
        [1] ✅ Включено
        *[0] ❌ Выключено
    }
    </blockquote>

    Работает только при включенной обязательной подписке на канал/группу.

msg-extra-mini-app-reserve =
    ⚙️ <b>Резервная кнопка подключения при активном Mini App</b>

    Под основной кнопкой «Подключиться» (открывает Mini App) добавляется резервная кнопка, открывающая страницу подписки в браузере. Полезно в регионах, где Telegram Mini App может быть недоступен из-за блокировок.

    <blockquote>
    <b>Статус:</b> { $enabled ->
        [1] ✅ Включено
        *[0] ❌ Выключено
    }
    </blockquote>

    Работает только при включённом Mini App (BOT_MINI_APP).

msg-admins-main = <b>👮‍♂️ Администраторы</b>


# Menu editor
msg-menu-editor-main =
    <b>🎛 Редактор кнопок главного меню</b>

    Выберите кнопку для редактирования.

msg-menu-editor-button =
    <b>🎛 Конфигуратор кнопки</b>

    <blockquote>
    • <b>Статус</b>: { $is_active ->
        [1] 🟢 Включена
        *[0] 🔴 Выключена
        }
    • <b>Текст</b>: { $text }
    • <b>Доступ</b>: { role }
    • <b>Видимость</b>: { $subscribers_only ->
        [1] 🔒 Только подписчики
        *[0] 👥 Все пользователи
        }
    • <b>Тип</b>: { button-type }
    • <b>Цвет</b>: { $color ->
        [primary] Основной
        [success] Зеленый
        [danger] Красный
        *[OTHER] Без цвета
        }
    { $type ->
        [TEXT] { empty }
       *[OTHER] • <b>Данные</b>: { $payload }
    }
    </blockquote>

    Выберите пункт для изменения.

msg-menu-editor-button-text =
    <b>🏷️ Изменить текст кнопки</b>

    Введите текст кнопки (максимум 32 символа) или ключ перевода.

msg-menu-editor-button-availability =
    <b>✴️ Изменить доступ к кнопке</b>

    Выберите роль для доступа к кнопке.

msg-menu-editor-button-type =
    <b>🔖 Изменить тип кнопки</b>

    Выберите тип кнопки.

msg-menu-editor-button-payload =
    <b>📄 Изменить данные кнопки</b>

    { $button_type ->
        [URL] Введите ссылку. Должна начинаться с <code>https://</code>.
        [COPY] Введите текст, который скопируется в буфер обмена при нажатии.
        [WEB_APP] Введите ссылку на веб-приложение. Должна начинаться с <code>https://</code>, ссылки <code>t.me</code> не поддерживаются.
        *[TEXT] Отправьте сообщение (поддерживается HTML). Можно прикрепить фото, видео, файл или стикер. Лимит: до 4096 символов без медиа, до 1024 символов с медиа.
    }

msg-menu-editor-button-color =
    <b>🎨 Изменить цвет кнопки</b>

    Выберите цвет кнопки.


# Gateways
msg-gateways-main = <b>🌐 Платежные системы</b>
msg-gateways-settings = <b>🌐 Конфигурация { gateway-type }</b>
msg-gateways-default-currency = <b>💸 Валюта по умолчанию</b>
msg-gateways-placement = <b>🔢 Изменить позиционирование</b>

msg-gateways-field =
    <b>🌐 Конфигурация { gateway-type }</b>

    Введите новое значение для { $field ->
        [display_name] отображаемого названия
       *[other] { $field }
    }.


# Referral
msg-referral-main =
    <b>👥 Реферальная система</b>

    <blockquote>
    • <b>Статус</b>: { $is_enable -> 
        [1] 🟢 Включена
        *[0] 🔴 Выключена
        }
    • <b>Тип награды</b>: { reward-type }
    • <b>Количество уровней</b>: { $referral_level }
    • <b>Условие начисления</b>: { accrual-strategy }
    • <b>Форма начисления</b>: { reward-strategy }
    </blockquote>

    Выберите пункт для изменения.

msg-referral-level =
    <b>🔢 Изменить уровень</b>

    Выберите максимальный уровень реферала.

msg-referral-reward-type =
    <b>🎀 Изменить тип награды</b>

    Выберите новый тип награды.
    
msg-referral-accrual-strategy =
    <b>📍 Изменить условие начисления</b>

    Выберите, в каком случае будет начисляться награда.


msg-referral-reward-strategy =
    <b>⚖️ Изменить форму начисления</b>

    Выберите способ расчета награды.


msg-referral-reward-level = { $level } уровень: { $value }{ $reward_strategy_type ->
    [AMOUNT] { $reward_type ->
        [POINTS] { space }{ $value -> 
            [one] балл
            [few] балла
            *[more] баллов
            }
        [EXTRA_DAYS] { space }доп. { $value -> 
            [one] день
            [few] дня
            *[more] дней
            }
        *[OTHER] { $reward_type }
    }
    [PERCENT] % { $reward_type ->
        [POINTS] баллов
        [EXTRA_DAYS] доп. дней
        *[OTHER] { $reward_type }
    }
    *[OTHER] { $reward_strategy_type }
    }
    
msg-referral-reward =
    <b>🎁 Изменить награду</b>

    <blockquote>
    { $reward }
    </blockquote>

    { $reward_strategy_type ->
        [AMOUNT] Введите количество { $reward_type ->
            [POINTS] баллов
            [EXTRA_DAYS] дней
            *[OTHER] { $reward_type }
        }
        [PERCENT] Введите процент от { $reward_type ->
            [POINTS] <u>стоимости подписки</u>
            [EXTRA_DAYS] <u>длительности подписки</u>
            *[OTHER] { $reward_type }
        }
        *[OTHER] { $reward_strategy_type }
    } (в формате: уровень=значение)


# Plans
msg-plans-main = <b>📦 Планы</b>

msg-plans-import = 
    <b>📦 Импортировать планы</b>

    Отправьте json файл для импорта.

msg-plans-export = 
    <b>📦 Экспортировать планы</b>

    Выберите планы для экспорта.

msg-plan-configurator =
    <b>📦 Конфигуратор плана</b>

    <blockquote>
    • <b>Название</b>: { $name }
    • <b>Тип</b>: { plan-type } { $is_trial ->
    [1] (Пробник)
    *[0] { space }
    }
    • <b>Доступ</b>: { availability-type }
    • <b>Статус</b>: { $is_active -> 
        [1] 🟢 Включен
        *[0] 🔴 Выключен
        }
    </blockquote>
    
    <blockquote>
    • <b>Лимит трафика</b>: { $is_unlimited_traffic -> 
        [1] { unlimited }
        *[0] { $traffic_limit }
        }
    • <b>Лимит устройств</b>: { $is_unlimited_devices -> 
        [1] { unlimited }
        *[0] { $device_limit }
        }
    </blockquote>

    Выберите пункт для изменения.

msg-plan-name =
    <b>🏷️ Изменить название</b>

    { $name ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $name }
    </blockquote>
    }

    Введите уникальное название плана или ключ перевода (максимум 32 символа).

msg-plan-description =
    <b>💬 Изменить описание</b>

    { $description ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $description }
    </blockquote>
    }

    Введите новое описание плана или ключ перевода.

msg-plan-tag =
    <b>📌 Изменить тег</b>

    { $tag ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $tag }
    </blockquote>
    }

    Введите новый тег плана (только латинские заглавные буквы, цифры и символ подчеркивания).

msg-plan-type =
    <b>🔖 Изменить тип</b>

    Выберите новый тип плана. Отметьте кнопкой «Пробник», чтобы предоставить данный план как пробный.

msg-plan-availability =
    <b>✴️ Изменить доступность</b>

    Выберите доступность плана.

msg-plan-traffic =
    <b>🌐 Изменить лимит и стратегию сброса трафика</b>

    Введите новый лимит трафика плана (в ГБ) и выберите стратегию его сброса.

msg-plan-devices =
    <b>📱 Изменить лимит устройств</b>

    Введите новый лимит устройств плана.

msg-plan-durations =
    <b>⏳ Длительности плана</b>

    Выберите длительность для изменения цены.

msg-plan-duration =
    <b>⏳ Добавить длительность плана</b>

    Введите новую длительность (в днях).

msg-plan-prices =
    <b>💰 Изменить цены длительности ({ $value ->
            [0] { unlimited }
            *[OTHER] { unit-day }
        })</b>

    Выберите валюту с ценой для изменения.

msg-plan-price =
    <b>💰 Изменить цену для длительности ({ $value ->
            [0] { unlimited }
            *[OTHER] { unit-day }
        })</b>

    Введите новую цену для валюты { $currency }.

msg-plan-allowed-users = 
    <b>👥 Изменить список разрешенных пользователей</b>

    Введите ID пользователя или Email для добавления в список.

msg-plan-squads =
    <b>🔗 Сквады</b>

    { $internal_squads ->
    [0] { space }
    *[HAS] <b>⏺️ Внутренние</b>: { $internal_squads }
    }

    { $external_squad ->
    [0] { space }
    *[HAS] <b>⏹️ Внешний</b>: { $external_squad }
    }

msg-plan-internal-squads =
    <b>⏺️ Изменить список внутренних сквадов</b>

    Выберите, какие внутренние группы будут присвоены этому плану.

msg-plan-external-squads =
    <b>⏹️ Изменить внешний сквад</b>

    Выберите, какая внешняя группа будет присвоена этому плану.


# Notifications
msg-notifications-main = <b>🔔 Настройка уведомлений</b>
msg-notifications-user = <b>👥 Пользовательские уведомления</b>
msg-notifications-system = <b>⚙️ Системные уведомления</b>

msg-notifications-system-type = 
    <b>🔔 { notification-type }</b>

    <blockquote>
    • <b>Статус</b>: { $is_active -> 
    [1] 🟢 Включено
    *[0] 🔴 Выключено
    }
    • <b>Маршрут</b>: { $has_route -> 
    [0] { unknown }
    *[HAS] { NUMBER($chat_id, useGrouping: 0) }{ $thread_id ->
        [0] { space }
        *[HAS] :{ NUMBER($thread_id, useGrouping: 0) }
        }
    }
    </blockquote>

msg-notifications-system-route = 
    <b>📡 Маршрут: { notification-type }</b>

    <blockquote>
    • <b>Чат ID</b>: { $chat_id ->
        [0] { unknown }
        *[HAS] <code>{ NUMBER($chat_id, useGrouping: 0) }</code>
        }
    • <b>Тред ID</b>: { $thread_id ->
        [0] { unknown }
        *[HAS] <code>{ NUMBER($thread_id, useGrouping: 0) }</code>
        }
    </blockquote>

    Если чат ID не задан — уведомление будет отправлено в Личные сообщения.
    
    Если тред ID не задан — уведомление будет отправлено в чат.


msg-notifications-system-default-route =
    <b>📡 Общий маршрут</b>

    <blockquote>
    • <b>Чат ID</b>: { $chat_id ->
        [0] { unknown }
        *[HAS] <code>{ NUMBER($chat_id, useGrouping: 0) }</code>
        }
    • <b>Тред ID</b>: { $thread_id ->
        [0] { unknown }
        *[HAS] <code>{ NUMBER($thread_id, useGrouping: 0) }</code>
        }
    </blockquote>

    Маршрут применяется ко всем системным уведомлениям, у которых не задан собственный маршрут.

    Если чат ID не задан — уведомление будет отправлено в Личные сообщения.

    Если тред ID не задан — уведомление будет отправлено в чат.


msg-notifications-system-route-chat-id =
    <b>💬 Изменить Чат ID</b>

    Введите ID группы (например: <code>-1001234567891</code>).

msg-notifications-system-route-thread-id =
    <b>📁 Изменить Тред ID</b>

    Введите ID треда (введите <code>0</code> чтобы сбросить).


# Subscription
msg-subscription-main = <b>💳 Подписка</b>
msg-subscription-plans = <b>📦 Выберите план</b>
msg-subscription-new-success = Чтобы начать пользоваться нашим сервисом, нажмите кнопку <code>`{ btn-subscription.connect }`</code> и следуйте инструкциям!
msg-subscription-renew-success = Ваша подписка продлена на { $added_duration }.

msg-subscription-plan = 
    <b>📦 Доступный план по ссылке</b>
    
    Вам доступен план <b>{ $name }</b> по ссылке. Нажмите кнопку ниже чтобы перейти к выбору длительности и способа оплаты.

    { $description ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $description }
    </blockquote>
    }

    { $purchase_type ->
    [RENEW] <i>⚠️ Текущая подписка будет <u>продлена</u> на выбранный срок.</i>
    [CHANGE] <i>⚠️ Текущая подписка будет <u>заменена</u> данным планом без пересчета оставшегося срока.</i>
    *[OTHER] { empty }
    }
    
msg-subscription-details =
    <b>{ $plan }</b>:
    <blockquote>
    { $description ->
    [0] { empty }
    *[HAS]
    { $description }
    }

    • <b>Лимит трафика</b>: { $traffic }
    • <b>Лимит устройств</b>: { $devices }
    { $period ->
    [0] { empty }
    *[HAS] • <b>Длительность</b>: { $period }
    }
    { $final_amount ->
    [0] { empty }
    *[HAS] • <b>Стоимость</b>: { frg-payment-amount }
    }
    </blockquote>
    
    { $discount_percent ->
    [0] { empty }
    *[HAS]
    <blockquote>
    <i>Цены указаны с учетом { $is_personal_discount ->
        [1] вашей персональной скидки { $discount_percent }%
        *[0] разовой скидки { $discount_percent }%
        }</i>
    </blockquote>
    }

msg-subscription-duration =
    <b>⏳ Выберите длительность</b>

    { msg-subscription-details }

    { $plan_is_modified ->
    [1] <i>ℹ️ Условия плана изменились с момента последней покупки — актуальные данные указаны выше.</i>
    *[0] { "" }
    }

msg-subscription-payment-method =
    <b>💳 Выберите способ оплаты</b>

    { msg-subscription-details }

    { $plan_is_modified ->
    [0] { empty }
    *[MODIFIED] <i>ℹ️ Условия плана изменились с момента последней покупки — актуальные данные указаны выше.</i>
    }

msg-subscription-confirm =
    <b>🛒 Подтверждение { $purchase_type ->
    [RENEW] продления
    [CHANGE] изменения
    *[OTHER] покупки
    } подписки</b>

    { msg-subscription-details }

    { $purchase_type ->
    [RENEW] <i>⚠️ Текущая подписка будет <u>продлена</u> на выбранный срок.</i>
    [CHANGE] <i>⚠️ Текущая подписка будет <u>заменена</u> выбранной без пересчета оставшегося срока.</i>
    *[OTHER] { empty }
    }

    { $plan_is_modified ->
    [0] { empty }
    *[MODIFIED] <i>ℹ️ Условия плана изменились с момента последней покупки — актуальные данные указаны выше.</i>
    }

msg-subscription-trial =
    <b>✅ Пробная подписка успешно получена!</b>

    { msg-subscription-new-success }

msg-subscription-success =
    <b>✅ Оплата прошла успешно!</b>

    { $purchase_type ->
    [NEW] { msg-subscription-new-success }
    [RENEW] { msg-subscription-renew-success }
    [CHANGE] { msg-subscription-change-success }
    *[OTHER] { $purchase_type }
    }

msg-subscription-change-success = 
    Ваша подписка была изменена.

    <b>{ $plan_name }</b>
    { frg-subscription }

msg-subscription-failed = 
    <b>❌ Произошла ошибка!</b>

    Не волнуйтесь, техподдержка уже уведомлена и свяжется с вами в ближайшее время. Приносим извинения за неудобства.


# Importer
msg-importer-main = <b>📥 Импорт пользователей</b>

msg-importer-from-xui =
    <b>📥 Импорт пользователей (3X-UI)</b>
    
    { $has_exported -> 
    [1]
    <b>🔍 Найдено</b>:
    <blockquote>
    Всего пользователей: { $total }
    С активной подпиской: { $active }
    С истекшей подпиской: { $expired }
    </blockquote>
    *[0]
    Импортируются все <b>активные</b> пользователи с <b>числовым</b> email.

    Рекомендуется заранее отключить пользователей, у которых в поле email отсутствует Telegram ID. Операция может занять значительное время в зависимости от количества пользователей.

    Отправьте файл базы данных (в формате .db).
    }

msg-importer-squads =
    <b>🔗 Список внутренних сквадов</b>

    Выберите, какие внутренние группы будут доступны импортированным пользователям.

msg-importer-import-completed =
    <b>📥 Импорт пользователей завершен</b>
    
    <b>📃 Информация</b>:
    <blockquote>
    • <b>Всего пользователей</b>: { $total_count }
    • <b>Успешно импортированы</b>: { $success_count }
    • <b>Не удалось импортировать</b>: { $failed_count }
    </blockquote>

msg-importer-sync-panel =
    <b>🌀 Синхронизация: панель → бот</b>

    Проходит по всем пользователям в RemnaWave. Если пользователь отсутствует в боте — создает его и импортирует подписку. Если пользователь есть в боте без подписки — импортирует подписку из панели. Если пользователь есть в боте с подпиской — обновляет данные.

msg-importer-sync-bot =
    <b>🤖 Синхронизация: бот → панель</b>

    Проходит по всем пользователям бота. Если у пользователя нет подписки в боте — пропускает его, панель не затрагивается. Если подписка есть, но пользователь отсутствует в панели — создает его. Если пользователь присутствует в панели — обновляет данные.

msg-importer-sync-panel-completed =
    <b>📥 Синхронизация панель → бот завершена</b>

    <b>📃 Информация</b>:
    <blockquote>
    Всего пользователей в панели: { $total_panel_users }
    Всего пользователей в боте: { $total_bot_users }

    Новые пользователи: { $added_users }
    Добавлены подписки: { $added_subscription }
    Обновлены подписки: { $updated }

    Ошибки при синхронизации: { $errors }
    </blockquote>

msg-importer-sync-bot-completed =
    <b>🔄 Синхронизация бот → панель завершена</b>

    <b>📃 Информация</b>:
    <blockquote>
    Всего пользователей в боте: { $total_bot_users }

    Обновлены в панели: { $updated }
    Пересозданы в панели: { $recreated }
    
    Без подписки (пропущены): { $skipped_no_subscription }
    Ошибки при синхронизации: { $errors }
    </blockquote>


# Promocodes
msg-promocodes-main = <b>🎟 Промокоды</b>

msg-promocode-configurator =
    <b>🎟 Конфигуратор промокода</b>

    <blockquote>
    • <b>Код</b>: <code>{ $code }</code>
    • <b>Тип</b>: { promocode-type }
    • <b>Доступ</b>: { availability-type }
    • <b>Статус</b>: { $is_active ->
        [1] 🟢 Включен
        *[0] 🔴 Выключен
        }
    • <b>Повторная активация</b>: { $is_reusable ->
        [1] Разрешена
        *[0] Запрещена
        }
    </blockquote>

    <blockquote>
    • <b>Награда</b>: { $reward }
    • <b>Действует до</b>: { $expires }
    • <b>Лимит активаций</b>: { $max_activations }
    </blockquote>

    Выберите пункт для изменения.

msg-promocode-input-code =
    <b>🏷️ Изменить код</b>

    { $code ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $code }
    </blockquote>
    }

    Отправьте свой уникальный код (от 3 до 16 символов).

msg-promocode-select-type =
    <b>🔖 Изменить тип награды</b>

    Выберите тип награды.

msg-promocode-input-reward =
    <b>🎁 Изменить награду</b>

    { $reward ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $reward }
    </blockquote>
    }

    { $promocode_type ->
    [DURATION] Введите количество <b>дней</b>, которые будут добавлены к подписке пользователя при активации (Значение <code>0</code> сделает подписку бессрочной).
    [TRAFFIC] Введите количество <b>гигабайт (ГБ)</b>, которые будут добавлены к лимиту трафика подписки (Значение <code>0</code> сделает трафик безлимитным).
    [DEVICES] Введите количество <b>устройств</b>, которые будут добавлены к лимиту подписки (Значение <code>0</code> снимет лимит устройств).
    [PERSONAL_DISCOUNT] Введите размер <b>персональной скидки</b> в процентах — от 1 до 100.
    [PURCHASE_DISCOUNT] Введите размер <b>скидки на покупку</b> в процентах — от 1 до 100.
    *[OTHER] Введите значение награды (целое число).
    }

msg-promocode-select-plan =
    <b>📦 Изменить план</b>

    Выберите тарифный план.

msg-promocode-select-plan-duration =
    <b>⏳ Изменить длительность</b>

    Выберите длительность плана.

msg-promocode-select-availability =
    <b>✴️ Изменить доступность</b>

    Выберите доступность промокода.

msg-promocode-input-expires =
    <b>⌛ Действует до</b>

    { $expires ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $expires }
    </blockquote>
    }

    Введите дату «ДД.ММ.ГГГГ» (или с временем «ДД.ММ.ГГГГ ЧЧ:ММ»), либо число — дни с момента создания.

    Время указывается в UTC.

msg-promocode-input-max-activations =
    <b>🔢 Изменить лимит активаций</b>

    { $max_activations ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $max_activations }
    </blockquote>
    }

    Введите максимальное количество активаций.

msg-promocode-input =
    <b>🎟 Промокод</b>

    Введите промокод.

msg-promocode-confirm =
    <b>🎟 Промокод <code>{ $promo_code }</code></b>

    🎁 Вы получите: { $reward_type ->
        [DURATION] { $reward ->
            [0] текущая подписка станет <b>бессрочной</b>.
            *[OTHER] <b>{ $reward } { $reward ->
                [one] день
                [few] дня
                *[more] дней
            }</b> к сроку текущей подписки.
        }
        [TRAFFIC] { $reward ->
            [0] <b>безлимитный трафик</b> в текущей подписке.
            *[OTHER] <b>{ $reward } ГБ</b> к лимиту трафика.
        }
        [DEVICES] { $reward ->
            [0] <b>безлимит по устройствам</b> в текущей подписке.
            *[OTHER] <b>{ $reward } { $reward ->
                [one] устройство
                [few] устройства
                *[more] устройств
            }</b> к лимиту устройств.
        }
        [SUBSCRIPTION] <b>новый план</b> подписки.
        [PERSONAL_DISCOUNT] постоянную <b>скидку { $reward }%</b> на все покупки.
        [PURCHASE_DISCOUNT] <b>скидку { $reward }%</b> на следующую покупку.
        *[OTHER] награду на ваш аккаунт.
    }
    
    { $show_reset_warning ->
        [1] ⚠️ <i>Бонус действует до следующего продления подписки — при продлении лимит вернется к значению плана.</i>
       *[0] { space }
    }
    { $will_replace_subscription ->
        [1] ⚠️ <i>У вас уже есть активная подписка. Она будет заменена новым планом, текущий остаток дней и трафик будут сброшены.</i>
       *[0] { space }
    }

    Нажмите <b>Подтвердить</b> для активации.


# Ad Links
msg-ad-links-main = <b>🎯 Рекламные ссылки</b>

msg-ad-link-configurator =
    <b>🎯 Конфигуратор рекламной ссылки</b>

    <blockquote>
    • <b>Название</b>: { $name ->
        [0] не задано
        *[HAS] { $name }
    }
    • <b>Код</b>: { $code ->
        [0] не задан
        *[HAS] <code>{ $code }</code>
    }
    • <b>Статус</b>: { $is_active ->
        [1] 🟢 Включена
        *[0] 🔴 Выключена
    }
    </blockquote>

    Выберите пункт для изменения.

msg-ad-link-name =
    <b>🏷️ Название ссылки</b>

    { $name ->
    [0] { space }
    *[HAS]
    <blockquote>{ $name }</blockquote>
    }

    Введите название рекламной кампании.

msg-ad-link-code =
    <b>🔗 Код ссылки</b>

    Текущий: <code>{ $code }</code>

    Отправьте свой уникальный код или нажмите.

msg-ad-link-stats =
    <b>📊 Статистика: { $name }</b>

    <blockquote>
    • <b>Регистрации</b>: { $registrations }
    • <b>Пробники</b>: { $trials }
    • <b>Покупки</b>: { $buyers }

    • <b>Конверсия регистрация → покупка</b>: { $reg_to_buy_rate }%
    • <b>Конверсия пробник → покупка</b>: { $trial_to_buy_rate }%
    </blockquote>

    <blockquote>
    { $revenue_lines }
    </blockquote>