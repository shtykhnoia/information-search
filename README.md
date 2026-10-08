# Поисковый движок по фильмам и сериалам

Сейчас реализован поисковый робот (лабораторная 2): он скачивает статьи русской Википедии и Викицитатника в MongoDB, продолжает обход после остановки и проверяет изменения. Анализ корпуса, индекс и поиск будут добавлены в следующих лабораторных. [Задания курса](https://github.com/toshunster/MAI-IR).

## Структура

```text
src/
  config.py       чтение и проверка YAML
  mediawiki.py    HTTP и MediaWiki API
  crawler.py      обход, сохранение и обновление документов
  search/         место для будущего поиска
configs/
  corpus.yaml     источники и настройки робота
tests/            проверки робота на локальном HTTP-сервере
scripts/test.py   запуск тестов
compose.yaml     MongoDB и интерфейс mongo-express
.work/           служебные материалы помощника, исходное задание и лекции
```

## Быстрый запуск

Python 3.12 работает в Windows, Docker Engine — в WSL Ubuntu. Docker Desktop не нужен. Команды ниже выполняются в PowerShell из `D:\IR`.

При первой установке Python-зависимостей:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Запустить базу и интерфейс, затем робота:

```powershell
wsl -d ubuntu --cd /mnt/d/IR docker compose up -d --wait
.venv/Scripts/python.exe -m src.crawler configs/corpus.yaml
```

По умолчанию робот обходит 12 названий из конфигурации и завершается. Полный обход категорий выключен. Если проект находится в другом месте, замените `/mnt/d/IR` на его путь внутри WSL.

## Посмотреть результат

Откройте [mongo-express](http://localhost:8081), выберите базу `film_lab2` и коллекцию `documents`. В документе видны название, URL и исходный HTML. Фильтр `{"source":"wikipedia"}` оставит только статьи Википедии.

В базе две коллекции:

- `documents` — документы: `url`, `html`, `source`, `title`, Unix-время скачивания `timestamp`, время последней проверки `checked_at`, ревизия и SHA-256. Идентификатор состоит из источника и `pageid`, поэтому перенаправления не создают дубликатов.
- `progress` — сохранённая порция названий, позиция `index`, продолжение API и признак завершения `done`.

MongoDB доступна из Windows по `mongodb://127.0.0.1:27017`. База и интерфейс опубликованы только на localhost, без пароля, для локальной лабораторной работы.

## Остановить и продолжить

Остановите робота через **Ctrl+C**. Для продолжения выполните ту же команду:

```powershell
.venv/Scripts/python.exe -m src.crawler configs/corpus.yaml
```

Робот сохраняет документ перед продвижением позиции обхода. После прерывания он повторяет текущую статью; сохранённые документы не теряются и не дублируются. На одну базу запускается один робот.

Управление контейнерами:

```powershell
wsl -d ubuntu --cd /mnt/d/IR docker compose ps
wsl -d ubuntu --cd /mnt/d/IR docker compose logs --tail 50
wsl -d ubuntu --cd /mnt/d/IR docker compose down
wsl -d ubuntu --cd /mnt/d/IR docker compose up -d --wait
```

Данные находятся в Docker volume `mai-ir_mongo-data` и сохраняются после `down` и перезапуска компьютера. Команда `down -v` удаляет этот том вместе с базой.

## Настройки робота

Робот принимает один аргумент — путь к YAML. Подключение задаётся в `db.uri` и `db.database`, источники — в `sources`.

| Настройка в `logic` | Назначение |
|---|---|
| `delay_seconds` | Пауза между началами HTTP-запросов |
| `timeout_seconds` | Таймаут запроса |
| `retries` | Повторы при временной сетевой ошибке |
| `recrawl_seconds` | Интервал повторной проверки статьи |
| `continuous` | Продолжать периодические проверки после обхода |
| `crawl_categories` | Дополнительно обойти статьи указанных категорий |

Для большого сбора включите `crawl_categories: true`. Для постоянного обновления — `continuous: true`. По умолчанию повторная проверка выполняется через сутки.

При неизменной ревизии MediaWiki HTML не скачивается. При изменении робот делает условный HTTP-запрос и сравнивает SHA-256. Только новое содержимое заменяет HTML и `timestamp`; `checked_at` обновляется при проверке. Изменения общих шаблонов без смены ревизии статьи таким способом не обнаруживаются.

Завершённые категории повторно не перечисляются. Отсутствующие и неоднозначные статьи пропускаются с объяснением. Ошибка HTTP после исчерпания повторов завершает процесс с кодом 1; следующий запуск продолжает с текущей статьи.

## Тесты

При работающей MongoDB:

```powershell
.venv/Scripts/python.exe scripts/test.py
```

Ожидаемый результат — `Ran 18 tests` и `OK`. Тесты используют локальный HTTP-сервер и отдельные временные базы `ir_test_*`, которые удаляются после проверки. Основная база не меняется; внешний интернет не нужен.

Проверяются сохранение HTML, пагинация, перенаправления, обновления, продолжение после принудительной остановки, ошибки HTTP/YAML, robots.txt и ограничение размера ответа. Для другой тестовой MongoDB задайте переменную `TEST_MONGO_URI`.

## Установка Docker в WSL с нуля

В этой рабочей среде установка уже выполнена. Для новой Ubuntu 22.04/24.04 откройте `wsl -d ubuntu` и выполните команды из [официальной инструкции Docker](https://docs.docker.com/engine/install/ubuntu/):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
```

Для обычного пользователя добавьте `sudo usermod -aG docker "$USER"` и заново войдите в WSL. В текущей Ubuntu используется root, поэтому это не требуется. Для `systemctl` нужен включённый systemd в `/etc/wsl.conf`: `[boot]` и `systemd=true`.

В текущей WSL не отвечал автоматически выданный DNS. В `/etc/wsl.conf` отключено создание `resolv.conf`, в `/etc/resolv.conf` указан DNS роутера `192.168.0.1`; при смене сети его может потребоваться заменить. Адреса репозиториев Ubuntu переведены с HTTP на HTTPS. Исходные настройки сохранены в `.work/*before-docker`.

Прежняя Windows-база сохранена в `data/mongodb`, её процесс остановлен. Контейнер использует отдельную базу; старые данные в него не переносились.
