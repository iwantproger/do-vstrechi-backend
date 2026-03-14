# Schedule Booking Backend API

Backend API для системы бронирования встреч Schedule Booking App.

## Технологии

- **FastAPI** - современный веб-фреймворк для Python
- **Supabase** - PostgreSQL база данных
- **Pydantic** - валидация данных

## Быстрый старт

### Локальная разработка

1. Установи зависимости:
```bash
pip install -r requirements.txt
```

2. Создай файл `.env`:
```bash
cp .env.example .env
```

3. Заполни `.env` своими данными:
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
```

4. Запусти сервер:
```bash
python main.py
```

Сервер запустится на http://localhost:8000

### Документация API

После запуска открой:
- http://localhost:8000/docs - Swagger UI
- http://localhost:8000/redoc - ReDoc

## API Endpoints

### Пользователи
- `POST /api/users/auth` - Авторизация пользователя

### Расписания
- `POST /api/schedules` - Создать расписание
- `GET /api/schedules` - Получить все расписания пользователя
- `GET /api/schedules/{id}` - Получить конкретное расписание

### Слоты
- `GET /api/available-slots/{schedule_id}?date=YYYY-MM-DD` - Доступные слоты

### Бронирования
- `POST /api/bookings` - Создать бронирование
- `GET /api/bookings` - Получить бронирования
- `PATCH /api/bookings/{id}/confirm` - Подтвердить
- `PATCH /api/bookings/{id}/cancel` - Отменить

### Статистика
- `GET /api/stats` - Получить статистику

## Деплой на Railway

1. Подключи репозиторий к Railway
2. Добавь переменные окружения
3. Railway автоматически задеплоит

## Структура проекта

```
backend-api/
├── main.py              # Основной файл приложения
├── requirements.txt     # Зависимости
├── .env.example        # Пример конфигурации
└── README.md           # Эта инструкция
```

## Лицензия

MIT
