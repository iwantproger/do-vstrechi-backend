"""
Backend API для Schedule Booking App - ИСПРАВЛЕННАЯ ВЕРСИЯ
С логированием и обработкой ошибок
"""

import os
import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from enum import Enum
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Schedule Booking API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")

logger.info(f"SUPABASE_URL: {SUPABASE_URL}")
logger.info(f"SUPABASE_KEY exists: {bool(SUPABASE_KEY)}")

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("SUPABASE credentials not found!")
    raise ValueError("Missing SUPABASE_URL or SUPABASE_ANON_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
logger.info("Supabase client created successfully")

# Модели данных
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
    duration: int
    buffer_time: int = 0
    work_hours_start: str
    work_hours_end: str
    work_days: List[int]
    video_platform: VideoPlatform

class BookingCreate(BaseModel):
    schedule_id: str
    guest_name: str
    guest_contact: str
    guest_telegram_id: Optional[int] = None
    scheduled_time: str
    notes: Optional[str] = None

# Middleware для логирования всех запросов
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url}")
    try:
        response = await call_next(request)
        logger.info(f"Response status: {response.status_code}")
        return response
    except Exception as e:
        logger.error(f"Request failed: {e}")
        raise

# Обработчик ошибок
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}")
    import traceback
    logger.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)}
    )

@app.get("/")
async def root():
    """Корневой эндпоинт"""
    return {
        "message": "Schedule Booking API",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health():
    """Проверка здоровья"""
    try:
        # Проверяем подключение к Supabase
        result = supabase.table('users').select("id").limit(1).execute()
        return {"status": "healthy", "supabase": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}

@app.post("/api/users/auth")
async def auth_user(user_data: UserAuth):
    """Авторизация/регистрация пользователя"""
    logger.info(f"Auth request for telegram_id: {user_data.telegram_id}")
    
    try:
        # Проверяем существует ли пользователь
        existing = supabase.table('users').select('*').eq(
            'telegram_id', user_data.telegram_id
        ).execute()
        
        logger.info(f"Existing user check: {len(existing.data)} found")
        
        if existing.data:
            # Обновляем данные
            updated = supabase.table('users').update({
                'username': user_data.username,
                'first_name': user_data.first_name,
                'last_name': user_data.last_name
            }).eq('telegram_id', user_data.telegram_id).execute()
            
            logger.info(f"User updated: {existing.data[0]['id']}")
            
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
                'last_name': user_data.last_name
            }).execute()
            
            logger.info(f"New user created: {new_user.data[0]['id']}")
            
            return {
                "success": True,
                "user_id": new_user.data[0]['id'],
                "is_new": True
            }
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/schedules")
async def create_schedule(schedule_data: ScheduleCreate):
    """Создание нового расписания"""
    logger.info(f"Creating schedule for telegram_id: {schedule_data.telegram_id}")
    logger.info(f"Schedule data: {schedule_data.model_dump()}")
    
    try:
        # Получаем user_id по telegram_id
        user = supabase.table('users').select('id').eq(
            'telegram_id', schedule_data.telegram_id
        ).execute()
        
        logger.info(f"User lookup result: {user.data}")
        
        if not user.data:
            logger.error(f"User not found for telegram_id: {schedule_data.telegram_id}")
            raise HTTPException(status_code=404, detail="User not found. Please /start the bot first.")
        
        user_id = user.data[0]['id']
        logger.info(f"Found user_id: {user_id}")
        
        # Создаем расписание
        schedule_insert_data = {
            'user_id': user_id,
            'title': schedule_data.title,
            'duration': schedule_data.duration,
            'buffer_time': schedule_data.buffer_time,
            'work_hours_start': schedule_data.work_hours_start,
            'work_hours_end': schedule_data.work_hours_end,
            'work_days': schedule_data.work_days,
            'video_platform': schedule_data.video_platform.value,
            'is_active': True
        }
        
        logger.info(f"Inserting schedule: {schedule_insert_data}")
        
        new_schedule = supabase.table('schedules').insert(schedule_insert_data).execute()
        
        logger.info(f"Schedule created: {new_schedule.data}")
        
        if not new_schedule.data:
            logger.error("Failed to create schedule - no data returned")
            raise HTTPException(status_code=500, detail="Failed to create schedule")
        
        return new_schedule.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Schedule creation error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error creating schedule: {str(e)}")

@app.get("/api/schedules")
async def get_schedules(telegram_id: int):
    """Получение всех расписаний пользователя"""
    logger.info(f"Getting schedules for telegram_id: {telegram_id}")
    
    try:
        # Получаем user_id
        user = supabase.table('users').select('id').eq('telegram_id', telegram_id).execute()
        
        if not user.data:
            return {"schedules": []}
        
        # Получаем расписания
        schedules = supabase.table('schedules').select('*').eq(
            'user_id', user.data[0]['id']
        ).eq('is_active', True).execute()
        
        logger.info(f"Found {len(schedules.data)} schedules")
        
        return {"schedules": schedules.data}
    except Exception as e:
        logger.error(f"Get schedules error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/schedules/{schedule_id}")
async def get_schedule(schedule_id: str):
    """Получение конкретного расписания"""
    logger.info(f"Getting schedule: {schedule_id}")
    
    try:
        schedule = supabase.table('schedules').select('*').eq('id', schedule_id).execute()
        
        if not schedule.data:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        return schedule.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get schedule error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/available-slots/{schedule_id}")
async def get_available_slots(schedule_id: str, date: str):
    """Получение доступных слотов"""
    logger.info(f"Getting slots for schedule {schedule_id} on {date}")
    
    try:
        # Получаем расписание
        schedule = supabase.table('schedules').select('*').eq('id', schedule_id).execute()
        
        if not schedule.data:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        schedule_data = schedule.data[0]
        target_date = datetime.fromisoformat(date)
        
        # Проверяем день недели
        day_of_week = target_date.weekday()
        if day_of_week not in schedule_data['work_days']:
            return {"date": date, "available_slots": []}
        
        # Генерация слотов
        start_time = datetime.strptime(schedule_data['work_hours_start'], "%H:%M").time()
        end_time = datetime.strptime(schedule_data['work_hours_end'], "%H:%M").time()
        work_start = datetime.combine(target_date.date(), start_time)
        work_end = datetime.combine(target_date.date(), end_time)
        
        duration = schedule_data['duration']
        buffer_time = schedule_data['buffer_time']
        interval = duration + buffer_time
        
        # Получаем существующие бронирования
        date_start = target_date.replace(hour=0, minute=0, second=0)
        date_end = target_date.replace(hour=23, minute=59, second=59)
        
        bookings = supabase.table('bookings').select('*').eq(
            'schedule_id', schedule_id
        ).gte('scheduled_time', date_start.isoformat()).lte(
            'scheduled_time', date_end.isoformat()
        ).neq('status', 'cancelled').execute()
        
        booked_times = set()
        for booking in bookings.data:
            booked_time = datetime.fromisoformat(booking['scheduled_time'].replace('Z', '+00:00'))
            booked_times.add(booked_time.strftime("%H:%M"))
        
        # Генерируем слоты
        slots = []
        current = work_start
        
        while current + timedelta(minutes=duration) <= work_end:
            if current > datetime.now():
                time_str = current.strftime("%H:%M")
                if time_str not in booked_times:
                    slots.append({
                        "time": time_str,
                        "datetime": current.isoformat()
                    })
            current += timedelta(minutes=interval)
        
        logger.info(f"Generated {len(slots)} available slots")
        
        return {"date": date, "available_slots": slots}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get slots error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bookings")
async def create_booking(booking_data: BookingCreate):
    """Создание бронирования"""
    logger.info(f"Creating booking for schedule: {booking_data.schedule_id}")
    
    try:
        # Получаем расписание
        schedule = supabase.table('schedules').select('*, users(telegram_id)').eq(
            'id', booking_data.schedule_id
        ).execute()
        
        if not schedule.data:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        schedule_info = schedule.data[0]
        
        # Проверяем конфликты
        existing = supabase.table('bookings').select('*').eq(
            'schedule_id', booking_data.schedule_id
        ).eq('scheduled_time', booking_data.scheduled_time).neq(
            'status', 'cancelled'
        ).execute()
        
        if existing.data:
            raise HTTPException(status_code=409, detail="This slot is already booked")
        
        # Генерируем ссылку
        booking_id = str(uuid.uuid4())
        
        if schedule_info['video_platform'] == 'jitsi':
            meeting_link = f"https://meet.jit.si/meeting-{booking_data.schedule_id[:8]}-{booking_id[:8]}"
        else:
            meeting_link = f"https://meet.example.com/{booking_id}"
        
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
        
        logger.info(f"Booking created: {booking_id}")
        
        result = new_booking.data[0]
        result['meeting_title'] = schedule_info['title']
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create booking error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bookings")
async def get_bookings(telegram_id: int, status: Optional[str] = None):
    """Получение бронирований"""
    logger.info(f"Getting bookings for telegram_id: {telegram_id}")
    
    try:
        query = supabase.table('bookings').select(
            '*, schedules(title, duration)'
        ).eq('organizer_telegram_id', telegram_id)
        
        if status:
            query = query.eq('status', status)
        
        bookings = query.order('scheduled_time', desc=False).execute()
        
        result = []
        for booking in bookings.data:
            if booking.get('schedules'):
                booking['meeting_title'] = booking['schedules']['title']
            result.append(booking)
        
        logger.info(f"Found {len(result)} bookings")
        
        return {"bookings": result}
        
    except Exception as e:
        logger.error(f"Get bookings error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/api/bookings/{booking_id}/cancel")
async def cancel_booking(booking_id: str):
    result = supabase.table('bookings').update(
        {'status': 'cancelled'}
    ).eq('id', booking_id).execute()
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting server...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
