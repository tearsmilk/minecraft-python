# Honoka

Лаунчер сервера Hoka на основе [лаунчера Horizon](https://github.com/horizon-rust/horizon/tree/main/launcher) (Minecraft Java Edition 26.3, переписанный на Rust, MIT). Кнопка **«Играть»** сразу запускает игру на `mc.hoka.ink`.

В репозитории нет копии Horizon. Здесь лежат только наши изменения:

| Путь | Что |
|---|---|
| `upstream.json` | Коммит Horizon, на котором мы стоим |
| `patches/0001-honoka-launcher.patch` | Наш патч поверх `launcher/` Horizon |
| `branding/links.json` | Сайт, Discord и адрес сервера. Лаунчер читает его при старте, поэтому адрес можно сменить без релиза |
| `scripts/honoka.py` | Скачать Horizon, наложить патч, собрать |
| `LICENSE-HORIZON` | Лицензия Horizon (MIT). Её нужно сохранять в форке |

## Что меняет патч

Всё Honoka-специфичное собрано в одном файле `launcher/src/honoka.rs`. Остальные правки короткие: ссылки из кода Horizon на этот файл.

- **«Играть» → сразу на сервер.** Если не выбран мир или друг, игра стартует с `--server mc.hoka.ink`. То же для Java-инстансов.
- **Старые серверы.** Игра запускается с `HORIZON_OLDER_SERVERS=1`. Это встроенный адаптер Horizon для серверов 1.21.11 и ниже, а Ферма на 1.21.11. Адаптер выбирается по пингу сервера. Как он поведёт себя за Velocity, ещё **не проверено**.
- **Название.** Окно, меню, папка установки и app id — Honoka / Honoka Launcher.
- **Свои папки.** Данные лаунчера лежат в `honoka-launcher`, игры и миры — в `honoka`. Поэтому Honoka и Horizon можно поставить рядом, они не мешают друг другу.
- **Ссылки и сервер** берутся из `branding/links.json` этого репозитория. Если файл недоступен (например, репозиторий приватный), используются встроенные значения из `honoka.rs`.
- **Автообновление выключено.** Иначе лаунчер Horizon заменил бы наш собой. Включим, когда будут свои подписанные релизы.

Что **не** меняется: сами сборки игры. Лаунчер, как и раньше, скачивает их из релизов Horizon и проверяет подписью Horizon. Файлы Mojang берутся из игры, установленной у игрока, или скачиваются у Mojang под его аккаунт. Мы их не храним и не раздаём.

## Сборка

Нужны git, Python 3.10+ и Rust (`rustup`, stable). На Windows ещё Visual Studio Build Tools (C++).

```bash
python scripts/honoka.py build
```

Готовый лаунчер появится в `dist/honoka-launcher` (на Windows `dist/honoka-launcher.exe`). Первая сборка долгая: тянется весь Horizon и его зависимости.

Быстрая проверка без сборки бинарника:

```bash
python scripts/honoka.py check
```

### Вход (обязательно для игры)

Лаунчер входит в Microsoft-аккаунт через Azure-приложение. Его client ID берётся при сборке из переменной `HORIZON_MSA_CLIENT_ID`. Без неё лаунчер собирается, но войти и играть в нём нельзя.

Приложение Horizon брать нельзя: это чужое приложение, и на экране согласия оно называется «Horizon». Нужно своё:

1. portal.azure.com → Microsoft Entra ID → App registrations → New registration. Имя `Honoka`, тип «Personal Microsoft accounts only», Allow public client flows: **Yes**.
2. Подать заявку Mojang на доступ к Minecraft API: https://aka.ms/mce-reviewappid. Пока её не одобрят, вход отвечает 403.
3. Собрать с ID:

```powershell
$env:HORIZON_MSA_CLIENT_ID = "<client id>"; python scripts/honoka.py build
```

Подробности — в `docs/microsoft-account.md` у Horizon.

## Обновление Horizon

```bash
python scripts/honoka.py bump <коммит Horizon>
```

```bash
python scripts/honoka.py sync
```

Если патч не встал, поправьте файлы в `upstream/launcher/` руками и выполните:

```bash
python scripts/honoka.py refresh
```

Эта команда перепишет `patches/` по тому, что сейчас лежит в `upstream/`. Для своих правок порядок такой: меняете `upstream/launcher/`, затем `refresh`, затем коммит.

## Дальше

- Своя иконка и логотип (`packaging/icons/horizon.ico` в Horizon, `launcher/assets/`).
- Переименовать бинарник и установщик (`horizon-launcher.exe`, `horizon-launcher-setup`).
- Свои релизы с подписью и включённое автообновление.
- Главная страница: новости и онлайн сервера, как на hoka.ink.
- Проверить вход на тестовую копию Фермы (Velocity → Limbo → Ферма 1.21.11).

Honoka — неофициальный проект, он не связан с Mojang, Microsoft и Horizon.
