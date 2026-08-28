btn-back =
    .general = ⬅️ Назад
    .menu = ↩️ Главное меню
    .menu-return = ↩️ Вернуться в главное меню
    .dashboard = ↩️ Вернуться в панель управления
    .referrals = 👪 К списку рефералов

btn-common =
    .notification-close = ❌ Закрыть
    .devices-empty = ⚠️ У вас нет подключенных устройств
    .cancel = Отмена
    .next = ▶️ Далее
    .prev = ◀️ Назад

    .squad-choice = { $selected -> 
    [1] 🔘
    *[0] ⚪
    } { $name }

    .duration = ⌛ { $value ->
    [0] { unlimited }
    *[OTHER] { unit-day }
    }

btn-devices =
    .delete-all = 🗑 Удалить все устройства
    .reissue = 🔄 Перевыпустить подписку
    .confirm-delete = ✅ Да, удалить
    .confirm-reissue = ✅ Да, сбросить
    .cancel-reissue = ❌ Нет

    .item = { $platform_icon } { $platform } { $device_model -> 
    [0] { space }
    *[HAS] ({ $device_model }){ space }
    }— { $created_at }

btn-backup =
    .active-toggle = { $enabled ->
        [1] 🟢 Включен
        *[0] 🔴 Выключен
    }
    .set-interval = 🕐 Интервал
    .set-max-files = 📁 Кол-во файлов
    .send-toggle = { $send_to_chat ->
        [1] ✅ Отправка в чат: включена
        *[0] ❌ Отправка в чат: выключена
    }
    .backup-assets = 📦 Запустить бэкап ассетов
    .backup-db = 🗄 Запустить бэкап базы данных
    
btn-remnashop-info =
    .release-latest = 👀 Посмотреть
    .how-upgrade = ❓ Как обновить
    .github = ⭐ GitHub
    .telegram = 👪 Telegram
    .donate = 💰 Поддержать разработчика
    .docs = 📖 Документация

btn-requirement =
    .rules-accept = ✅ Принять правила
    .channel-join = ❤️ Перейти в канал
    .channel-confirm = ✅ Подтвердить

btn-menu =
    .trial = 🎁 ПОПРОБОВАТЬ БЕСПЛАТНО
    .trial-paid = 🚀 ПОПРОБОВАТЬ ЗА { $trial_price }
    .connect = 🚀 Подключиться
    .connect-reserve = 🔗 Подключиться (резерв)
    .devices = 📱 Устройства
    .subscription = 💳 Подписка
    .invite = 👥 Пригласить
    .support = 🆘 Поддержка
    .web-cabinet = 🌐 Личный кабинет
    .dashboard = 🛠 Панель управления

    .connect-not-available =
    ⚠️ { $status ->
    [LIMITED] ПРЕВЫШЕН ЛИМИТ ТРАФИКА
    [EXPIRED] СРОК ДЕЙСТВИЯ ИСТЕК
    *[OTHER] ВАША ПОДПИСКА НЕ РАБОТАЕТ
    } ⚠️

btn-invite =
    .about = ❓ Подробнее о награде
    .copy = 📋 Скопировать ссылку
    .send = 📩 Пригласить
    .qr = 🧾 QR-код
    .withdraw-points = 💎 Обменять баллы
    .reset-referral = 🔄 Сбросить реф. ссылку

btn-dashboard =
    .statistics = 📊 Статистика
    .users = 👥 Пользователи
    .broadcast = 📢 Рассылка
    .promocodes = 🎟 Промокоды
    .access = 🔓 Режим доступа
    .remnawave = 🌊 RemnaWave
    .remnashop = 🛍 RemnaShop
    .transactions = 🧾 Транзакции
    .importer = 📥 Импорт пользователей

btn-statistics =
    .users = 👥 Пользователи
    .subscriptions = 💳 Подписки
    .transactions = 🧾 Транзакции
    .promocodes = 🎁 Промокоды
    .referrals = 👪 Рефералы

    .subscription-page =
    { $page ->
        [0] { $is_current ->
            [1] [ Общая статистика ]
            *[0] Общая статистика
        }
        *[OTHER] { $is_current ->
            [1] [ { $plan_name } ]
            *[0] { $plan_name }
        }
    }

    .transaction-page =
    { $page ->
        [0] { $is_current ->
            [1] [ Общая статистика ]
            *[0] Общая статистика
        }
        *[OTHER] { $is_current ->
            [1] [ { gateway-type } ]
            *[0] { gateway-type }
        }
    }

btn-users =
    .search = 🔍 Поиск пользователя
    .recent-registered = 🆕 Последние зарегистрированные
    .recent-activity = 📝 Последние взаимодействующие
    .blacklist = 🚫 Черный список
    .unblock-all = 🔓 Разблокировать всех
    .blacklist-view = 🗒️ Список заблокированных
    .blacklist-block = ⛔ Заблокировать по ID
    .blacklist-sources = 🔗 Автообновляемые списки
    .blacklist-sources-sync = 🔄 Синхронизировать
    .blacklist-block-clear = 🗑 Очистить список ID

    .blacklist-source = 🔗 { $source }

btn-user =
    .discount = 💸 Скидка
    .discount-personal = 👤 Персональная скидка
    .discount-purchase = 🎟 На следующую покупку
    .points = 💎 Баллы
    .statistics = 📊 Статистика
    .referrals = 👪 Рефералы
    .message = 📩 Сообщение
    .role = 👮‍♂️ Роль
    .transactions = 🧾 Транзакции
    .give-access = 🔑 Доступ к планам
    .current-subscription = 💳 Текущая подписка
    .subscription-traffic-limit = 🌐 Лимит трафика
    .subscription-device-limit = 📱 Лимит устройств
    .subscription-expire-time = ⏳ Время истечения
    .subscription-squads = 🔗 Сквады
    .subscription-traffic-reset = 🔄 Сбросить трафик
    .subscription-devices = 🗒️ Список устройств
    .subscription-url = 📋 Скопировать ссылку
    .subscription-delete = ❌ Удалить
    .subscription-reissue = ♻️ Перевыпустить
    .message-preview = 👀 Предпросмотр
    .message-confirm = ✅ Отправить
    .referral-reset = 🔄 Сбросить реф. ссылку
    .sync = 🌀 Синхронизировать
    .sync-remnawave = 🌊 Использовать данные Remnawave
    .sync-remnashop = 🛍 Использовать данные Remnashop
    .give-subscription = 🎁 Выдать подписку
    .subscription-internal-squads = ⏺️ Внутренние сквады
    .subscription-external-squads = ⏹️ Внешний сквад

    .allowed-plan-choice = { $selected ->
    [1] 🔘
    *[0] ⚪
    } { $plan_name }

    .subscription-active-toggle = { $is_active ->
    [1] 🔴 Выключить
    *[0] 🟢 Включить
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
    [1] 🧪 Пробник: доступен
    *[0] 🧪 Пробник: не доступен
    }

    .block = { $is_blocked ->
    [1] 🔓 Разблокировать
    *[0] 🔒 Заблокировать
    }

btn-broadcast =
    .list = 🗒️ Список всех рассылок
    .all = 👥 Всем
    .plan = 📦 По плану
    .subscribed = ✅ С подпиской
    .unsubscribed = ❌ Без подписки
    .expired = ⌛ Просроченным
    .trial = ✳️ С пробником
    .content = ✉️ Редактировать содержимое
    .buttons = ✳️ Редактировать кнопки
    .preview = 👀 Предпросмотр
    .confirm = ✅ Запустить рассылку
    .refresh = 🔄 Обновить данные
    .cancel = ⛔ Остановить рассылку
    .delete = ❌ Удалить отправленное

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
    .subscription = 💳 Купить подписку
    .promocode = 🎟 Активировать промокод
    .invite = 👥 Пригласить
    .subscription-renew = 🔄 Продлить подписку
    .user-profile = 👤 Перейти к пользователю
    .referrer-profile = 🤝 Перейти к пригласителю
    .contact-support = 📩 Перейти в поддержку

btn-promocodes =
    .save = ✅ Сохранить
    .create = 🆕 Создать промокод
    .confirm = ✅ Создать промокод
    .delete = 🗑️ Удалить
    .regenerate = 🔄 Перегенерировать
    .code = 🏷️ Код
    .type = 🔖 Тип награды
    .availability = ✴️ Доступ
    .reward = 🎁 Награда
    .plan = 📦 План
    .expires = ⌛ Срок действия
    .max-activations = 🔢 Лимит активаций
    .reset = 🔄 Сбросить

    .plan-duration = { $days -> 
        [one] { $days } день
        [few] { $days } дня
        *[more] { $days } дней
    }

    .item = 🎟 { $code } — { promocode-type }

    .active-toggle = { $is_active ->
    [1] 🟢 Включен
    *[0] 🔴 Выключен
    }

    .reusable-toggle = 🔁 { $is_reusable ->
    [1] Повтор: да
    *[0] Повтор: нет
    }

btn-access =
    .mode = { access-mode }
    .conditions = ⚙️ Условия доступа
    .rules = ✳️ Принятие правил
    .channel = ❇️ Подписка на канал

    .payments-toggle = { $enabled ->
    [1] 🔘
    *[0] ⚪
    } Платежи

    .registration-toggle = { $enabled ->
    [1] 🔘
    *[0] ⚪
    } Регистрация

    .condition-toggle = { $enabled ->
    [1] 🔘 Включено
    *[0] ⚪ Выключено
    }

btn-remnashop =
    .admins = 👮‍♂️ Администраторы
    .gateways = 🌐 Платежные системы
    .referral = 👥 Реф. система
    .advertising = 🎯 Реклама
    .plans = 📦 Планы
    .notifications = 🔔 Уведомления
    .logs = 📄 Логи
    .menu-editor = 🎛 Редактор главного меню
    .backup = 💾 Бэкап
    .extra = ⚙️ Доп. настройки

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
    } Удаление устройства

    .device-all = { $enabled -> 
        [1] 🟢
        *[0] 🔴
    } Удаление всех устройств

    .link-reset = { $enabled -> 
        [1] 🟢
        *[0] 🔴
    } Перевыпуск подписки
    .referral-reset = { $enabled -> 
        [1] 🟢
        *[0] 🔴
    } Сброс реф. ссылки

    .trial-channel-guard = { $enabled ->
        [1] 🟢
        *[0] 🔴
    } Авто отключение пробника

    .mini-app-reserve = { $enabled ->
        [1] 🟢
        *[0] 🔴
    } Резервная кнопка подключения

    .toggle = { $enabled ->
        [1] 🟢 Включено
        *[0] 🔴 Выключено
    }

btn-menu-editor =
    .text = 🏷️ Текст
    .availability = ✴️ Доступ
    .type = 🔖 Тип
    .payload = 📄 Данные
    .color = 🎨 Цвет
    .confirm = ✅ Сохранить
    .color-default = Без цвета
    .color-primary = Основной
    .color-success = Зеленый
    .color-danger = Красный

    .button = { $is_active ->
        [1] 🟢
        *[0] 🔴
    } { $text }

    .active-toggle = { $is_active ->
        [1] 🟢 Включена
        *[0] 🔴 Выключена
    }

    .subscribers-only-toggle = { $subscribers_only ->
        [1] 💳 С подпиской
        *[0] 👥 Всем
    }

btn-gateway =
    .title = { gateway-type }
    .setting = { $field }
    .display-name = 🏷️ Отображаемое название
    .webhook-copy = 📋 Скопировать вебхук
    .test = 🐞 Тест
    .default-currency = 💸 Валюта по умолчанию
    .placement = 🔢 Изменить позиционирование
    .field-reset = ♻️ Сбросить значение

    .active-toggle = { $is_active ->
    [1] 🟢 Включено
    *[0] 🔴 Выключено
    }

    .default-currency-choice = { $enabled ->
    [1] 🔘
    *[0] ⚪
    } { $symbol } { $currency }

btn-referral =
    .level = 🔢 Уровень
    .reward-type = 🎀 Тип награды
    .accrual-strategy = 📍 Условие начисления
    .reward-strategy = ⚖️ Форма начисления
    .reward = 🎁 Награда
    
    .active-toggle = { $is_enable -> 
    [1] 🟢 Включена
    *[0] 🔴 Выключена
    }

    .level-choice = { $type -> 
    [1] 1️⃣
    [2] 2️⃣
    [3] 3️⃣
    *[OTHER] { $type }
    }

    .reward-choice = { $type -> 
    [POINTS] 💎 Баллы
    [EXTRA_DAYS] ⏳ Дни
    *[OTHER] { $type }
    }

    .accrual-strategy-choice = { $type -> 
    [ON_FIRST_PAYMENT] 💳 Первый платеж
    [ON_EACH_PAYMENT] 💸 Каждый платеж
    *[OTHER] { $type }
    }

    .reward-strategy-choice = { $type -> 
    [AMOUNT] 🔸 Фиксированная
    [PERCENT] 🔹 Процентная
    *[OTHER] { $type }
    }

btn-notifications =
    .user = 👥 Пользовательские
    .system = ⚙️ Системные
    .route = 📡 Маршрут
    .default-route = 📡 Общий маршрут
    .chat-id = 💬 Изменить чат
    .thread-id = 📁 Изменить тред
    .route-clear = ❌ Удалить маршрут
    
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
    [1] 🟢 Включено
    *[0] 🔴 Выключено
    }

btn-plans =
    .save = ✅ Сохранить
    .create = 🆕 Создать план
    .create-confirm = ✅ Создать план
    .delete = ❌ Удалить
    .name = 🏷️ Название
    .description = 💬 Описание
    .description-remove = ❌ Удалить текущее описание
    .tag = 📌 Тег
    .tag-remove = ❌ Удалить текущий тег
    .type = 🔖 Тип
    .availability = ✴️ Доступ
    .durations-prices = ⏳ Длительности и 💰 Цены
    .traffic = 🌐 Трафик
    .devices = 📱 Устройства
    .allowed = 👥 Разрешенные пользователи
    .squads = 🔗 Сквады
    .internal-squads = ⏺️ Внутренние сквады
    .external-squads = ⏹️ Внешний сквад
    .duration-add = 🆕 Добавить длительность
    .price-choice = 💸 { $price } { $currency }
    .export = 📤 Экспорт
    .import = 📥 Импорт
    .exporting = 📤 Экспортировать
    .importing = 📥 Импортировать
    .url = 📋 Скопировать ссылку на план

    .trial = { $is_trial ->
    [1] 🔘
    *[0] ⚪
    } Пробник 

    .export-choice = { $selected ->
    [1] 🔘
    *[0] ⚪
    } { $name }

    .title = { $is_active ->
    [1] 🟢
    *[0] 🔴 
    } { $name }

    .active-toggle = { $is_active -> 
    [1] 🟢 Включен
    *[0] 🔴 Выключен
    }
    
    .type-choice = { $type -> 
    [TRAFFIC] 🌐 Трафик
    [DEVICES] 📱 Устройства
    [BOTH] 🔗 Трафик + устройства
    [UNLIMITED] ♾️ Безлимит
    *[OTHER] { $type }
    }

    .availability-choice = { $type -> 
    [ALL] 🌍 Для всех
    [NEW] 🌱 Для новых
    [EXISTING] 👥 Для клиентов
    [INVITED] ✉️ Для приглашенных
    [ALLOWED] 🔐 Для разрешенных
    [LINK] 🔗 По ссылке
    *[OTHER] { $type }
    }

    .traffic-strategy-choice = { $selected ->
    [1] 🔘 { traffic-strategy }
    *[0] ⚪ { traffic-strategy }
    }

    
btn-remnawave =
    .users = 👥 Пользователи
    .hosts = 🌐 Хосты
    .nodes = 🖥️ Ноды
    .inbounds = 🔌 Инбаунды

btn-importer =
    .from-xui = 💩 Импорт из панели 3X-UI
    .sync-from-panel = 🌀 Синхронизация: панель → бот
    .sync-from-bot = 🤖 Синхронизация: бот → панель
    .sync-start = ▶️ Синхронизировать
    .squads = 🔗 Внутренние сквады
    .import-all = ✅ Импортировать всех
    .import-active = ❇️ Импортировать активных

btn-subscription =
    .plan = 💳 Перейти к оформлению подписки
    .new = 💸 Купить подписку
    .renew = 🔄 Продлить
    .change = 🔃 Изменить
    .promocode = 🎟 Активировать промокод
    .promocode-confirm = ✅ Подтвердить
    .pay = 💳 Оплатить
    .get = 🎁 Получить бесплатно
    .back-plans = ⬅️ Назад к выбору плана
    .back-duration = ⬅️ Изменить длительность
    .back-payment-method = ⬅️ Изменить способ оплаты
    .connect = 🚀 Подключиться

    .payment-method = { $gateway_title } | { $final_amount ->
    [0] 🎁
    *[HAS] { $final_amount }{ $currency }
    }
    
    .duration = { $period } | { $final_amount -> 
    [0] 🎁
    *[HAS] { $final_amount }{ $currency }
    }

btn-ad-links =
    .save = ✅ Сохранить
    .create = 🆕 Создать ссылку
    .create-confirm = ✅ Создать ссылку
    .delete = ❌ Удалить ссылку
    .name = 🏷️ Название
    .code = 🔗 Код
    .regenerate = 🔄 Перегенерировать
    .stats = 📊 Статистика
    .url = 📋 Скопировать ссылку

    .title = { $is_active ->
    [1] 🟢
    *[0] 🔴
    } { $name }

    .active-toggle = { $is_active ->
    [1] 🟢 Включена
    *[0] 🔴 Выключена
    }