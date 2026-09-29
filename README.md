# subdomain-enum

CLI-утилита для пассивного поиска поддоменов с резолвингом текущих IP-адресов.
Проект реализован в стиле Clean Architecture: доменная модель и бизнес-логика
отделены от вывода и сетевых адаптеров.

## Возможности

- Поиск поддоменов по домену с пассивных источников: crt.sh, HackerTarget и
  AnubisDB.
- Резолвинг IP через стандартный `socket.gethostbyname` без внешних системных
  команд.
- Вывод в текстовом и JSON-формате (`--json`).
- Сохранение результатов в файл через `-o/--output`.
- Ограничение списка источников через `--sources`.
- Параллельная обработка источников и DNS-резолвинга.
- Устойчивость к падению отдельных источников: один сбой не прерывает весь поиск.

## Архитектура проекта

```text
.
├── src/
│   ├── __init__.py
│   ├── main.py          # точка входа, запускает CLI
│   ├── interface.py     # argparse + сборка зависимостей
│   ├── services.py      # порты, реализации источников, резолвер, use case
│   └── models.py        # доменная сущность Subdomain
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_services.py
│   └── test_interface.py
├── Dockerfile
├── pyproject.toml
└── README.md
```

Логика расположена так:

- `src/models.py` — доменная сущность `Subdomain` и константа `NOT_APPLICABLE`.
- `src/services.py` — интерфейсы (`SubdomainSource`, `DnsResolver`, `ResultWriter`),
  реализации источников, форматтеры, `EnumerateSubdomainsUseCase`.
- `src/interface.py` — CLI и сборка зависимостей через `argparse`.
- `src/main.py` — точка входа для запуска приложения и утилиты в `pip`-скрипте.

## Установка и запуск

### Локально (рекомендуется)

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# Unix / Git Bash
source .venv/bin/activate

pip install -e ".[dev]"
subdomain-enum example.com
```

### Прямой запуск Python

```bash
python -m subdomain_enum.main example.com
python -m subdomain_enum.main example.com --json
python -m subdomain_enum.main example.com --sources crtsh hackertarget -o result.json --json
```

### Через Docker

```bash
docker build -t subdomain-enum .
docker run --rm subdomain-enum example.com --json
```

## Примеры вывода

### Текстовый формат

```text
$ subdomain-enum example.com
[*] Searching subdomains for example.com...
Subdomains found: 3

api.example.com                                   93.184.216.34
example.com                                       93.184.216.34
www.example.com                                    N/A
```

### JSON

```json
[
  {
    "subdomain": "api.example.com",
    "ip": "93.184.216.34"
  },
  {
    "subdomain": "example.com",
    "ip": "93.184.216.34"
  },
  {
    "subdomain": "www.example.com",
    "ip": "N/A"
  }
]
```

## Как это работает

Поиск является пассивным: утилита не brute-force-атакует DNS и не перебирает
словарные списки. Она собирает данные из публичных источников и фильтрует их по
принадлежности искомому домену.

1. `CrtShSource` читает данные из `crt.sh` и извлекает имена из `name_value`.
2. `HackerTargetSource` обрабатывает CSV-ответ API `hostsearch`.
3. `AnubisDbSource` парсит JSON-список с поддоменами.
4. Все имена нормализуются и дедуплицируются.
5. Для каждого уникального имени выполняется DNS-резолвинг через `socket`.
6. Результат форматируется либо в текст, либо в JSON и может быть сохранён в файл.

Ошибки отдельных источников или таймауты не прерывают сканирование: каждый
источник возвращает пустое множество в случае сбоя, а use-case продолжает работу.

## Разработка и проверка

### Тесты

```bash
pytest -q
```

### Линтинг

```bash
ruff check .
ruff format .
```

## Ограничения

- Резолвинг поддерживает IPv4 через `socket.gethostbyname`.
- Источники ограничены бесплатными публичными API без ключей.
- Для расширения можно добавить новый класс, реализующий `SubdomainSource`, и
  зарегистрировать его в `AVAILABLE_SOURCES` внутри `services.py`.
