"""
Backend API — Schedule Booking App v2.0
Fix: slot filtering uses utcnow() to be consistent with naive datetimes
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Schedule Booking API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_ANON_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
logger.info("Supabase client created")


# ============================================================
# MODELS
# ============================================================

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


# ============================================================
# MIDDLEWARE
# ============================================================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"{request.method} {request.url}")
    try:
        response = await call_next(request)
        logger.info(f"→ {response.status_code}")
        return response
    except Exception as e:
        logger.error(f"Request failed: {e}")
        raise

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    logger.error(f"Global exception: {exc}\n{traceback.format_exc()}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# ============================================================
# HEALTH
# ============================================================

@app.get("/")
async def root():
    return {"message": "Schedule Booking API", "version": "2.0.0", "status": "running"}

@app.get("/health")
async def health():
    try:
        supabase.table('users').select("id").limit(1).execute()
        return {"status": "healthy", "supabase": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


# ============================================================
# USERS
# ============================================================

@app.post("/api/users/auth")
async def auth_user(user_data: UserAuth):
    logger.info(f"Auth: telegram_id={user_data.telegram_id}")
    try:
        existing = supabase.table('users').select('*').eq('telegram_id', user_data.telegram_id).execute()

        if existing.data:
            supabase.table('users').update({
                'username': user_data.username,
                'first_name': user_data.first_name,
                'last_name': user_data.last_name
            }).eq('telegram_id', user_data.telegram_id).execute()
            return {"success": True, "user_id": existing.data[0]['id'], "is_new": False}
        else:
            new_user = supabase.table('users').insert({
                'telegram_id': user_data.telegram_id,
                'username': user_data.username,
                'first_name': user_data.first_name,
                'last_name': user_data.last_name
            }).execute()
            return {"success": True, "user_id": new_user.data[0]['id'], "is_new": True}

    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# SCHEDULES
# ============================================================

@app.post("/api/schedules")
async def create_schedule(schedule_data: ScheduleCreate):
    logger.info(f"Create schedule for telegram_id={schedule_data.telegram_id}")
    try:
        user = supabase.table('users').select('id').eq('telegram_id', schedule_data.telegram_id).execute()
        if not user.data:
            raise HTTPException(status_code=404, detail="User not found. Send /start to the bot first.")

        user_id = user.data[0]['id']
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

        logger.info(f"Schedule created: {new_schedule.data[0]['id']}")
        return new_schedule.data[0]

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Create schedule error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/schedules")
async def get_schedules(telegram_id: int):
    try:
        user = supabase.table('users').select('id').eq('telegram_id', telegram_id).execute()
        if not user.data:
            return {"schedules": []}

        schedules = supabase.table('schedules').select('*').eq(
            'user_id', user.data[0]['id']
        ).eq('is_active', True).execute()

        return {"schedules": schedules.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/schedules/{schedule_id}")
async def get_schedule(schedule_id: str):
    try:
        schedule = supabase.table('schedules').select('*').eq('id', schedule_id).execute()
        if not schedule.data:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return schedule.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# AVAILABLE SLOTS — Issue 3 fix: use utcnow() consistently
# ============================================================

@app.get("/api/available-slots/{schedule_id}")
async def get_available_slots(schedule_id: str, date: str):
    logger.info(f"Get slots for schedule={schedule_id} date={date}")
    try:
        schedule_result = supabase.table('schedules').select('*').eq('id', schedule_id).execute()
        if not schedule_result.data:
            raise HTTPException(status_code=404, detail="Schedule not found")

        schedule_data = schedule_result.data[0]
        target_date = datetime.fromisoformat(date)

        # Check work day
        day_of_week = target_date.weekday()
        if day_of_week not in schedule_data['work_days']:
            return {"date": date, "available_slots": []}

        # Parse work hours
        start_time = datetime.strptime(schedule_data['work_hours_start'], "%H:%M").time()
        end_time = datetime.strptime(schedule_data['work_hours_end'], "%H:%M").time()
        work_start = datetime.combine(target_date.date(), start_time)
        work_end = datetime.combine(target_date.date(), end_time)

        duration = schedule_data['duration']
        buffer_time = schedule_data['buffer_time']
        interval = duration + buffer_time

        # Get existing bookings for this day
        date_start = target_date.replace(hour=0, minute=0, second=0)
        date_end = target_date.replace(hour=23, minute=59, second=59)

        bookings = supabase.table('bookings').select('*').eq(
            'schedule_id', schedule_id
        ).gte('scheduled_time', date_start.isoformat()).lte(
            'scheduled_time', date_end.isoformat()
        ).neq('status', 'cancelled').execute()

        booked_times = set()
        for booking in bookings.data:
            try:
                bt = datetime.fromisoformat(booking['scheduled_time'].replace('Z', '').replace('+00:00', ''))
                booked_times.add(bt.strftime("%H:%M"))
            except Exception:
                pass

        # Generate slots
        # FIX Issue 3: use utcnow() — server stores times as UTC-naive
        # Frontend additionally filters by user's local time
        now_utc = datetime.utcnow()

        slots = []
        current = work_start

        while current + timedelta(minutes=duration) <= work_end:
            # Only show future slots (UTC comparison — consistent with naive datetimes)
            if current > now_utc:
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
        import traceback
        logger.error(f"Get slots error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# BOOKINGS
# ============================================================

@app.post("/api/bookings")
async def create_booking(booking_data: BookingCreate):
    logger.info(f"Create booking for schedule={booking_data.schedule_id}")
    try:
        schedule = supabase.table('schedules').select('*, users(telegram_id)').eq(
            'id', booking_data.schedule_id
        ).execute()

        if not schedule.data:
            raise HTTPException(status_code=404, detail="Schedule not found")

        schedule_info = schedule.data[0]

        # Check conflict
        existing = supabase.table('bookings').select('*').eq(
            'schedule_id', booking_data.schedule_id
        ).eq('scheduled_time', booking_data.scheduled_time).neq('status', 'cancelled').execute()

        if existing.data:
            raise HTTPException(status_code=409, detail="This slot is already booked")

        booking_id = str(uuid.uuid4())

        # Generate meeting link
        if schedule_info['video_platform'] == 'jitsi':
            meeting_link = f"https://meet.jit.si/meeting-{schedule_info['id'][:8]}-{booking_id[:8]}"
        else:
            meeting_link = f"https://meet.example.com/{booking_id}"

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
        import traceback
        logger.error(f"Create booking error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bookings")
async def get_bookings(telegram_id: int, status: Optional[str] = None):
    logger.info(f"Get bookings for telegram_id={telegram_id}")
    try:
        query = supabase.table('bookings').select(
            '*, schedules(title, duration)'
        ).eq('organizer_telegram_id', telegram_id)

        if status:
            query = query.eq('status', status)

        bookings = query.order('scheduled_time', desc=False).execute()

        result = []
        for b in bookings.data:
            if b.get('schedules'):
                b['meeting_title'] = b['schedules']['title']
            result.append(b)

        return {"bookings": result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
