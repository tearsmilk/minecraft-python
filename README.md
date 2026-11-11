# Honoka

Лаунчер сервера Hoka на Python. Одна кнопка **«Играть»** запускает [Horizon](https://github.com/horizon-rust/horizon) (Minecraft: Java Edition 26.3, переписанный на Rust) сразу на `mc.hoka.ink`.

Работает только на стандартной библиотеке Python 3.9+: окно на tkinter, сеть на urllib, подпись Ed25519 проверяется на чистом Python. Ставить ничего не нужно.

```bash
python -m honoka
```

Это открывает окно. Есть и консольные команды: `python -m honoka login`, `play`, `status`, `logout`.

## Как это устроено

Лаунчер работает по официальному [Launch API Horizon для сторонних лаунчеров](https://github.com/horizon-rust/horizon/blob/main/docs/api/launch-guide.md):

1. **Вход** (`account.py`). Код входа Microsoft → Xbox Live → XSTS → сервисы Minecraft. Затем проверка, **что на аккаунте куплена Java Edition**: без этого игра не запускается. Это то же правило «только для владельца», что и у Horizon. Токены на Windows защищены через DPAPI, на других системах лежат в файле, доступном только пользователю.
2. **Сборка Horizon** (`builds.py`). Берётся последний релиз `horizon-rust/horizon` для этой системы. `SHA256SUMS` проверяется по подписи Ed25519 ключом Horizon, архив — по SHA-256. После этого он распаковывается.
3. **Файлы игры** (`mojang.py`) скачиваются только для владельца:
   - версия, client jar, библиотеки и ресурсы 26.3 — с серверов Mojang, каждый файл сверяется с sha1. Если игра уже установлена у игрока, файлы копируются оттуда;
   - server jar нужен для первой подготовки;
   - Java 25 — та, что уже установлена у игрока, иначе Java от Mojang.
4. **Подготовка** (`game.py`). `horizon-prepare --check`, а если ресурсы не готовы — `--prepare --complete --progress json`.
5. **Запуск.** `horizon-client --quickPlayMultiplayer mc.hoka.ink --session-stdin`. Сессия передаётся через stdin, никогда в командной строке. Также задаётся `HORIZON_OLDER_SERVERS=1`: это адаптер Horizon для сервера 1.21.11.

Файлы Mojang и Horizon не хранятся в этом репозитории и не раздаются. Всё скачивается на компьютер игрока под его аккаунт.

Адрес сервера и ссылки лежат в `branding/links.json`, лаунчер читает их при старте. Если файл недоступен, используются значения из `honoka/config.py`.

### Где лежат данные

Windows `%APPDATA%\Honoka`, macOS `~/Library/Application Support/Honoka`, Linux `~/.local/share/honoka`. Переопределяется переменной `HONOKA_HOME`.

## Системы

| Система | Сборка Horizon |
|---|---|
| Windows 10/11 x64, ARM64 | `horizon-windows-*.zip` |
| macOS 12+ (Apple Silicon, Intel) | `horizon-macos-*.zip` |
| **macOS 11 Intel** | `horizon-macos-x64.zip` — см. ниже |
| Linux x86_64 | `horizon-linux-x86_64.tar.gz` |

**macOS 11 на Intel.**
- Официально Horizon поддерживает macOS 12+. Но его Intel-программы (`horizon-client`, `horizon-prepare`) собраны с минимумом **macOS 10.12**: это видно в заголовке Mach-O `LC_VERSION_MIN_MACOSX` (проверено на Nightly от 11.11.2026). Поэтому на macOS 11 они запускаются.
- Honoka работает на macOS 11 и показывает предупреждение. Системы старше 11 не поддерживаются.
- Для подготовки ресурсов нужна Java 25. Лаунчер сначала ищет установленную у игрока (`/Library/Java/JavaVirtualMachines`, `JAVA_HOME` или `java_home` в `settings.json`) и только потом качает Java от Mojang. Если Java от Mojang на macOS 11 не запустится, поставьте Temurin 25 с adoptium.net.
- Python для macOS 11 — установщик с python.org: в нём есть tkinter.
- На реальном Mac с macOS 11 это **ещё не проверялось**.

## Временный вход через лаунчер Horizon (пока ждём Azure)

Пока в `config.py` нет своего client ID, Honoka входит через **официальный лаунчер Horizon**: у него уже есть одобренное приложение Microsoft.

1. Поставить лаунчер Horizon с playhorizon.dev и войти в нём аккаунтом Microsoft, на котором куплена Java Edition.
2. Запустить Honoka и нажать «Играть».

Honoka спрашивает у лаунчера Horizon:
- аккаунт: `horizon-launcher --json account list`. Нужен выбранный аккаунт и `owner: true`;
- сессию для игры: `horizon-launcher --json account session <uuid>`. Файл сессии читается один раз и сразу удаляется.

Проверка владения остаётся за Horizon. Лаунчер ищется в стандартной папке установки. Если он стоит в другом месте, путь задаётся через `HONOKA_HORIZON_LAUNCHER` или `horizon_launcher` в `settings.json`.

Как только в `config.py` появится свой client ID, Honoka сам переключится на свой вход.

Режима совсем без входа нет и не будет: Horizon можно запускать только владельцам игры. Игроки без лицензии заходят на сервер как раньше: Java-клиент + Fabric + мод Hoka.

## Вход (обязательно для игры)

Нужно своё приложение Azure. Приложение Horizon брать нельзя: оно чужое и на экране согласия называется «Horizon».

1. portal.azure.com → Microsoft Entra ID → App registrations → New registration. Имя `Honoka`, тип «Personal Microsoft accounts only». В Authentication включить **Allow public client flows**.
2. Подать заявку Mojang на доступ к Minecraft API: https://aka.ms/mce-reviewappid. Пока её не одобрят, вход отвечает «приложение ещё не одобрено Mojang».
3. Вписать client ID в `MSA_CLIENT_ID` в `honoka/config.py`. Для проверки можно вместо этого задать переменную `HONOKA_MSA_CLIENT_ID`.

## Разработка

```bash
python -m unittest discover -s tests
```

Тесты проверяют:
- Ed25519 на векторе RFC 8032 и на настоящей подписи Nightly Horizon (`tests/fixtures`);
- выбор сборки под систему, включая Intel Mac;
- распаковку архива (пути вида `..` отбрасываются);
- правила библиотек Mojang и чтение версии Java;
- определение macOS (Python, собранный со старым SDK, показывает macOS 11 как 10.16);
- хранение аккаунта;
- запуск: сервер в аргументах, сессия только в stdin.

## Дальше

- Client ID Azure и одобрение Mojang.
- Сборка в один файл на каждую систему (PyInstaller) и иконка.
- Проверить вход на тестовую копию Фермы (Velocity → Limbo → Ферма 1.21.11).
- Проверить на настоящем Mac с macOS 11 Intel.
- Новости и онлайн сервера в окне.

Honoka — неофициальный проект, он не связан с Mojang, Microsoft и Horizon.
