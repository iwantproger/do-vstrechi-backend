"""
Backend API для Schedule Booking App
FastAPI приложение для работы с базой данных
"""

import os
import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from enum import Enum

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Инициализация FastAPI
app = FastAPI(title="Schedule Booking API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене замени на конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase клиент
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# =============================================================================
# МОДЕЛИ ДАННЫХ (Pydantic)
# =============================================================================

class VideoPlatform(str, Enum):
    jitsi = "jitsi"
    google_meet = "google_meet"
    zoom = "zoom"
    yandex = "yandex"
    mts = "mts"


class BookingStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    completed = "completed"


class UserAuth(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class ScheduleCreate(BaseModel):
    telegram_id: int
    title: str
    duration: int  # минуты
    buffer_time: int = 0  # минуты
    work_hours_start: str  # "09:00"
    work_hours_end: str  # "18:00"
    work_days: List[int]  # [0,1,2,3,4] = Пн-Пт
    video_platform: VideoPlatform


class ScheduleResponse(BaseModel):
    id: str
    title: str
    duration: int
    buffer_time: int
    work_hours_start: str
    work_hours_end: str
    work_days: List[int]
    video_platform: str
    created_at: str


class BookingCreate(BaseModel):
    schedule_id: str
    guest_name: str
    guest_contact: str
    guest_telegram_id: Optional[int] = None
    scheduled_time: str  # ISO format
    notes: Optional[str] = None


class BookingResponse(BaseModel):
    id: str
    schedule_id: str
    meeting_title: str
    guest_name: str
    guest_contact: str
    scheduled_time: str
    status: BookingStatus
    meeting_link: Optional[str] = None
    created_at: str


class AvailableSlot(BaseModel):
    time: str
    datetime: str


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def generate_meeting_link(platform: str, schedule_id: str, booking_id: str) -> str:
    """Генерация ссылки на видеовстречу"""
    
    if platform == "jitsi":
        # Jitsi - просто генерируем уникальную комнату
        room_name = f"meeting-{schedule_id}-{booking_id}"
        return f"https://meet.jit.si/{room_name}"
    
    elif platform == "google_meet":
        # Google Meet - в реальности нужен OAuth, пока заглушка
        return f"https://meet.google.com/new"
    
    elif platform == "zoom":
        # Zoom - требует API ключей, пока заглушка
        return "https://zoom.us/j/placeholder"
    
    elif platform == "yandex":
        # Яндекс.Телемост
        return "https://telemost.yandex.ru/j/placeholder"
    
    elif platform == "mts":
        # МТС Линк
        return "https://link.mts.ru/j/placeholder"
    
    return ""


def calculate_available_slots(
    schedule: dict,
    target_date: datetime,
    existing_bookings: List[dict]
) -> List[AvailableSlot]:
    """Вычисление доступных слотов на указанную дату"""
    
    # Проверяем, что день недели входит в рабочие дни
    day_of_week = target_date.weekday()
    if day_of_week not in schedule['work_days']:
        return []
    
    # Парсим рабочие часы
    start_time = datetime.strptime(schedule['work_hours_start'], "%H:%M").time()
    end_time = datetime.strptime(schedule['work_hours_end'], "%H:%M").time()
    
    # Создаем datetime для начала и конца
    work_start = datetime.combine(target_date.date(), start_time)
    work_end = datetime.combine(target_date.date(), end_time)
    
    duration = schedule['duration']
    buffer_time = schedule['buffer_time']
    slot_interval = duration + buffer_time
    
    # Генерируем все возможные слоты
    all_slots = []
    current_time = work_start
    
    while current_time + timedelta(minutes=duration) <= work_end:
        all_slots.append(current_time)
        current_time += timedelta(minutes=slot_interval)
    
    # Получаем занятые слоты из существующих бронирований
    booked_times = []
    for booking in existing_bookings:
        if booking['status'] != 'cancelled':
            booked_time = datetime.fromisoformat(booking['scheduled_time'].replace('Z', '+00:00'))
            booked_times.append(booked_time)
    
    # Фильтруем свободные слоты
    available_slots = []
    for slot in all_slots:
        # Проверяем, что слот в будущем
        if slot <= datetime.now():
            continue
        
        # Проверяем конфликты с существующими встречами
        is_available = True
        for booked_time in booked_times:
            # Слот занят если он пересекается с существующей встречей
            if (slot <= booked_time < slot + timedelta(minutes=duration)) or \
               (booked_time <= slot < booked_time + timedelta(minutes=duration)):
                is_available = False
                break
        
        if is_available:
            available_slots.append(AvailableSlot(
                time=slot.strftime("%H:%M"),
                datetime=slot.isoformat()
            ))
    
    return available_slots


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    """Корневой эндпоинт"""
    return {
        "message": "Schedule Booking API",
        "version": "1.0.0",
        "status": "running"
    }


@app.post("/api/users/auth")
async def auth_user(user_data: UserAuth):
    """Авторизация/регистрация пользователя"""
    
    # Проверяем существует ли пользователь
    existing = supabase.table('users').select('*').eq(
        'telegram_id', user_data.telegram_id
    ).execute()
    
    if existing.data:
        # Обновляем данные
        updated = supabase.table('users').update({
            'username': user_data.username,
            'first_name': user_data.first_name,
            'last_name': user_data.last_name
        }).eq('telegram_id', user_data.telegram_id).execute()
        
        return {
            "success": True,
            "user_id": existing.data[0]['id'],
            "is_new": False
        }
    else:
        # Создаем нового пользователя
        new_user = supabase.table('users').insert({
            'telegram_id': user_data.telegram_id,
            'username': user_data.username,
            'first_name': user_data.first_name,
            'last_name': user_data.last_name,
            'role': 'organizer'  # По умолчанию
        }).execute()
        
        return {
            "success": True,
            "user_id": new_user.data[0]['id'],
            "is_new": True
        }


@app.post("/api/schedules", response_model=ScheduleResponse)
async def create_schedule(schedule_data: ScheduleCreate):
    """Создание нового расписания"""
    
    # Получаем user_id по telegram_id
    user = supabase.table('users').select('id').eq(
        'telegram_id', schedule_data.telegram_id
    ).execute()
    
    if not user.data:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_id = user.data[0]['id']
    
    # Создаем расписание
    new_schedule = supabase.table('schedules').insert({
        'user_id': user_id,
        'title': schedule_data.title,
        'duration': schedule_data.duration,
        'buffer_time': schedule_data.buffer_time,
        'work_hours_start': schedule_data.work_hours_start,
        'work_hours_end': schedule_data.work_hours_end,
        'work_days': schedule_data.work_days,
        'video_platform': schedule_data.video_platform.value,
        'is_active': True
    }).execute()
    
    if not new_schedule.data:
        raise HTTPException(status_code=500, detail="Failed to create schedule")
    
    return new_schedule.data[0]


@app.get("/api/schedules")
async def get_schedules(telegram_id: int):
    """Получение всех расписаний пользователя"""
    
    # Получаем user_id
    user = supabase.table('users').select('id').eq(
        'telegram_id', telegram_id
    ).execute()
    
    if not user.data:
        return {"schedules": []}
    
    # Получаем расписания
    schedules = supabase.table('schedules').select('*').eq(
        'user_id', user.data[0]['id']
    ).eq('is_active', True).execute()
    
    return {"schedules": schedules.data}


@app.get("/api/schedules/{schedule_id}")
async def get_schedule(schedule_id: str):
    """Получение конкретного расписания"""
    
    schedule = supabase.table('schedules').select('*').eq(
        'id', schedule_id
    ).execute()
    
    if not schedule.data:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    return schedule.data[0]


@app.get("/api/available-slots/{schedule_id}")
async def get_available_slots(schedule_id: str, date: str):
    """Получение доступных слотов на указанную дату"""
    
    # Получаем расписание
    schedule = supabase.table('schedules').select('*').eq(
        'id', schedule_id
    ).execute()
    
    if not schedule.data:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    schedule_data = schedule.data[0]
    
    # Парсим дату
    try:
        target_date = datetime.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    
    # Получаем существующие бронирования на эту дату
    date_start = target_date.replace(hour=0, minute=0, second=0)
    date_end = target_date.replace(hour=23, minute=59, second=59)
    
    bookings = supabase.table('bookings').select('*').eq(
        'schedule_id', schedule_id
    ).gte('scheduled_time', date_start.isoformat()).lte(
        'scheduled_time', date_end.isoformat()
    ).execute()
    
    # Вычисляем доступные слоты
    available_slots = calculate_available_slots(
        schedule_data,
        target_date,
        bookings.data
    )
    
    return {
        "date": date,
        "available_slots": available_slots
    }


@app.post("/api/bookings", response_model=BookingResponse)
async def create_booking(booking_data: BookingCreate):
    """Создание нового бронирования"""
    
    # Получаем расписание
    schedule = supabase.table('schedules').select('*, users(telegram_id)').eq(
        'id', booking_data.schedule_id
    ).execute()
    
    if not schedule.data:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    schedule_info = schedule.data[0]
    
    # Проверяем доступность слота
    scheduled_time = datetime.fromisoformat(booking_data.scheduled_time)
    
    # Проверяем конфликты
    existing = supabase.table('bookings').select('*').eq(
        'schedule_id', booking_data.schedule_id
    ).eq('scheduled_time', booking_data.scheduled_time).neq(
        'status', 'cancelled'
    ).execute()
    
    if existing.data:
        raise HTTPException(status_code=409, detail="This slot is already booked")
    
    # Генерируем ссылку на встречу
    booking_id = str(uuid.uuid4())
    meeting_link = generate_meeting_link(
        schedule_info['video_platform'],
        booking_data.schedule_id,
        booking_id
    )
    
    # Создаем бронирование
    new_booking = supabase.table('bookings').insert({
        'id': booking_id,
        'schedule_id': booking_data.schedule_id,
        'organizer_telegram_id': schedule_info['users']['telegram_id'],
        'guest_name': booking_data.guest_name,
        'guest_contact': booking_data.guest_contact,
        'guest_telegram_id': booking_data.guest_telegram_id,
        'scheduled_time': booking_data.scheduled_time,
        'status': 'pending',
        'meeting_link': meeting_link,
        'notes': booking_data.notes
    }).execute()
    
    if not new_booking.data:
        raise HTTPException(status_code=500, detail="Failed to create booking")
    
    result = new_booking.data[0]
    result['meeting_title'] = schedule_info['title']
    
    return result


@app.get("/api/bookings")
async def get_bookings(telegram_id: int, status: Optional[str] = None):
    """Получение списка бронирований"""
    
    query = supabase.table('bookings').select(
        '*, schedules(title, duration)'
    ).eq('organizer_telegram_id', telegram_id)
    
    if status:
        query = query.eq('status', status)
    
    bookings = query.order('scheduled_time', desc=False).execute()
    
    # Обогащаем данными о встрече
    result = []
    for booking in bookings.data:
        booking['meeting_title'] = booking['schedules']['title']
        result.append(booking)
    
    return {"bookings": result}


@app.patch("/api/bookings/{booking_id}/confirm")
async def confirm_booking(booking_id: str):
    """Подтверждение бронирования"""
    
    updated = supabase.table('bookings').update({
        'status': 'confirmed'
    }).eq('id', booking_id).execute()
    
    if not updated.data:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    return updated.data[0]


@app.patch("/api/bookings/{booking_id}/cancel")
async def cancel_booking(booking_id: str):
    """Отмена бронирования"""
    
    updated = supabase.table('bookings').update({
        'status': 'cancelled',
        'cancelled_at': datetime.now().isoformat()
    }).eq('id', booking_id).execute()
    
    if not updated.data:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    return updated.data[0]


@app.get("/api/stats")
async def get_stats(telegram_id: int):
    """Получение статистики"""
    
    # Получаем расписания
    user = supabase.table('users').select('id').eq(
        'telegram_id', telegram_id
    ).execute()
    
    if not user.data:
        return {"total_schedules": 0}
    
    schedules = supabase.table('schedules').select('id').eq(
        'user_id', user.data[0]['id']
    ).execute()
    
    # Получаем встречи
    now = datetime.now().isoformat()
    
    completed = supabase.table('bookings').select('id', count='exact').eq(
        'organizer_telegram_id', telegram_id
    ).eq('status', 'completed').execute()
    
    upcoming = supabase.table('bookings').select('id', count='exact').eq(
        'organizer_telegram_id', telegram_id
    ).eq('status', 'confirmed').gte('scheduled_time', now).execute()
    
    pending = supabase.table('bookings').select('id', count='exact').eq(
        'organizer_telegram_id', telegram_id
    ).eq('status', 'pending').execute()
    
    return {
        "total_schedules": len(schedules.data),
        "completed_meetings": completed.count,
        "upcoming_meetings": upcoming.count,
        "pending_meetings": pending.count
    }


# =============================================================================
# WEBHOOK для уведомлений (опционально)
# =============================================================================

@app.post("/api/webhooks/booking-created")
async def webhook_booking_created(booking_id: str):
    """Webhook для обработки новых бронирований"""
    
    # Здесь можно вызвать функцию отправки уведомления в Telegram
    # В продакшене это должно быть через очередь задач (Celery/RQ)
    
    booking = supabase.table('bookings').select(
        '*, schedules(title, duration)'
    ).eq('id', booking_id).execute()
    
    if booking.data:
        # Отправка уведомления организатору
        # await send_booking_notification(booking.data[0])
        pass
    
    return {"status": "processed"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
