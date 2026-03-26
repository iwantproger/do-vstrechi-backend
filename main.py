"""
Backend API для Schedule Booking App — v1.1.0
"""

import os
import uuid
from datetime import datetime, timedelta
from typing import List, Optional
import logging

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Schedule Booking API", version="1.1.0")

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
logger.info("Supabase connected")


# ──────────────────────────────────────────────────────────────
# MODELS
# ──────────────────────────────────────────────────────────────

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
    work_hours_start: str = "09:00"
    work_hours_end: str = "18:00"
    work_days: List[int] = [0, 1, 2, 3, 4]
    video_platform: str = "jitsi"
    location_mode: str = "fixed"
    description: Optional[str] = None
    requires_approval: bool = False

class BookingCreate(BaseModel):
    schedule_id: str
    guest_name: str
    guest_contact: str
    guest_telegram_id: Optional[int] = None
    scheduled_time: str
    notes: Optional[str] = None
    location_type: Optional[str] = None

class BookingCancel(BaseModel):
    reason: Optional[str] = None


# ──────────────────────────────────────────────────────────────
# MIDDLEWARE
# ──────────────────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"{request.method} {request.url.path}")
    response = await call_next(request)
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    logger.error(f"Unhandled: {exc}\n{traceback.format_exc()}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# ──────────────────────────────────────────────────────────────
# ROOT & HEALTH
# ──────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "Schedule Booking API", "version": "1.1.0", "status": "running"}

@app.get("/health")
async def health():
    try:
        supabase.table("users").select("id").limit(1).execute()
        return {"status": "healthy", "supabase": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


# ──────────────────────────────────────────────────────────────
# USERS
# ──────────────────────────────────────────────────────────────

@app.post("/api/users/auth")
async def auth_user(user_data: UserAuth):
    try:
        existing = supabase.table("users").select("*").eq("telegram_id", user_data.telegram_id).execute()
        if existing.data:
            supabase.table("users").update({
                "username": user_data.username,
                "first_name": user_data.first_name,
                "last_name": user_data.last_name,
            }).eq("telegram_id", user_data.telegram_id).execute()
            return {"success": True, "user_id": existing.data[0]["id"], "is_new": False}
        new_user = supabase.table("users").insert({
            "telegram_id": user_data.telegram_id,
            "username": user_data.username,
            "first_name": user_data.first_name,
            "last_name": user_data.last_name,
        }).execute()
        return {"success": True, "user_id": new_user.data[0]["id"], "is_new": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────
# SCHEDULES
# ──────────────────────────────────────────────────────────────

@app.post("/api/schedules")
async def create_schedule(schedule_data: ScheduleCreate):
    try:
        user = supabase.table("users").select("id").eq("telegram_id", schedule_data.telegram_id).execute()
        if not user.data:
            raise HTTPException(status_code=404, detail="User not found. Send /start to the bot first.")
        user_id = user.data[0]["id"]

        new_schedule = supabase.table("schedules").insert({
            "user_id": user_id,
            "title": schedule_data.title,
            "description": schedule_data.description,
            "duration": schedule_data.duration,
            "buffer_time": schedule_data.buffer_time,
            "work_hours_start": schedule_data.work_hours_start,
            "work_hours_end": schedule_data.work_hours_end,
            "work_days": schedule_data.work_days,
            "video_platform": schedule_data.video_platform,
            "location_mode": schedule_data.location_mode,
            "requires_approval": schedule_data.requires_approval,
            "is_active": True,
        }).execute()

        if not new_schedule.data:
            raise HTTPException(status_code=500, detail="Failed to create schedule")
        return new_schedule.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/schedules")
async def get_schedules(telegram_id: int):
    try:
        user = supabase.table("users").select("id").eq("telegram_id", telegram_id).execute()
        if not user.data:
            return {"schedules": []}
        schedules = supabase.table("schedules").select("*").eq(
            "user_id", user.data[0]["id"]
        ).eq("is_active", True).execute()
        return {"schedules": schedules.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/schedules/{schedule_id}")
async def get_schedule(schedule_id: str):
    try:
        schedule = supabase.table("schedules").select("*").eq("id", schedule_id).execute()
        if not schedule.data:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return schedule.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, telegram_id: int = Query(...)):
    try:
        user = supabase.table("users").select("id").eq("telegram_id", telegram_id).execute()
        if not user.data:
            raise HTTPException(status_code=404, detail="User not found")
        supabase.table("schedules").update({"is_active": False}).eq("id", schedule_id).eq(
            "user_id", user.data[0]["id"]
        ).execute()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────
# AVAILABLE SLOTS
# ──────────────────────────────────────────────────────────────

@app.get("/api/available-slots/{schedule_id}")
async def get_available_slots(schedule_id: str, date: str):
    try:
        schedule = supabase.table("schedules").select("*").eq("id", schedule_id).execute()
        if not schedule.data:
            raise HTTPException(status_code=404, detail="Schedule not found")

        sch = schedule.data[0]
        target_date = datetime.fromisoformat(date)

        # weekday(): 0=Mon..6=Sun  — совпадает с нашим форматом work_days
        day_of_week = target_date.weekday()
        if day_of_week not in sch["work_days"]:
            return {"date": date, "available_slots": []}

        start_time = datetime.strptime(sch["work_hours_start"], "%H:%M").time()
        end_time   = datetime.strptime(sch["work_hours_end"], "%H:%M").time()
        work_start = datetime.combine(target_date.date(), start_time)
        work_end   = datetime.combine(target_date.date(), end_time)

        duration    = int(sch["duration"])
        buffer_time = int(sch.get("buffer_time", 0))
        interval    = duration + buffer_time

        # Existing bookings
        date_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        date_end   = target_date.replace(hour=23, minute=59, second=59, microsecond=0)

        bookings = supabase.table("bookings").select("scheduled_time").eq(
            "schedule_id", schedule_id
        ).gte("scheduled_time", date_start.isoformat()).lte(
            "scheduled_time", date_end.isoformat()
        ).neq("status", "cancelled").execute()

        booked_times = set()
        for b in bookings.data:
            try:
                t = datetime.fromisoformat(b["scheduled_time"].replace("Z", "+00:00"))
                booked_times.add(t.strftime("%H:%M"))
            except Exception:
                pass

        now = datetime.now()
        slots = []
        current = work_start
        while current + timedelta(minutes=duration) <= work_end:
            if current > now:
                time_str = current.strftime("%H:%M")
                if time_str not in booked_times:
                    slots.append({"time": time_str, "datetime": current.isoformat()})
            current += timedelta(minutes=interval)

        return {"date": date, "available_slots": slots}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Slots error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────
# BOOKINGS
# ──────────────────────────────────────────────────────────────

@app.post("/api/bookings")
async def create_booking(booking_data: BookingCreate):
    try:
        schedule = supabase.table("schedules").select(
            "*, users(telegram_id, first_name)"
        ).eq("id", booking_data.schedule_id).execute()

        if not schedule.data:
            raise HTTPException(status_code=404, detail="Schedule not found")
        sch = schedule.data[0]

        # Conflict check
        existing = supabase.table("bookings").select("id").eq(
            "schedule_id", booking_data.schedule_id
        ).eq("scheduled_time", booking_data.scheduled_time).neq("status", "cancelled").execute()

        if existing.data:
            raise HTTPException(status_code=409, detail="This time slot is already booked")

        location_type = booking_data.location_type or sch.get("video_platform", "jitsi")
        booking_id = str(uuid.uuid4())
        meeting_link = _generate_meeting_link(location_type, booking_id, booking_data.schedule_id)

        requires_approval = sch.get("requires_approval", False)
        status = "pending" if requires_approval else "confirmed"

        organizer_tg_id = None
        if sch.get("users"):
            organizer_tg_id = sch["users"].get("telegram_id")

        new_booking = supabase.table("bookings").insert({
            "id": booking_id,
            "schedule_id": booking_data.schedule_id,
            "organizer_telegram_id": organizer_tg_id,
            "guest_name": booking_data.guest_name,
            "guest_contact": booking_data.guest_contact,
            "guest_telegram_id": booking_data.guest_telegram_id,
            "scheduled_time": booking_data.scheduled_time,
            "duration_minutes": sch.get("duration"),
            "status": status,
            "meeting_link": meeting_link,
            "location_type": location_type,
            "notes": booking_data.notes,
        }).execute()

        if not new_booking.data:
            raise HTTPException(status_code=500, detail="Failed to create booking")

        result = new_booking.data[0]
        result["meeting_title"] = sch.get("title")
        return result

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Create booking: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bookings")
async def get_bookings(telegram_id: int, status: Optional[str] = None):
    """
    Возвращает все бронирования пользователя:
    - как гость (guest_telegram_id)
    - как организатор (organizer_telegram_id)
    """
    try:
        results = []
        seen_ids = set()

        for field in ("guest_telegram_id", "organizer_telegram_id"):
            q = supabase.table("bookings").select(
                "*, schedules(title, duration)"
            ).eq(field, telegram_id)
            if status:
                q = q.eq("status", status)
            data = q.order("scheduled_time", desc=False).execute()
            for b in (data.data or []):
                if b["id"] not in seen_ids:
                    seen_ids.add(b["id"])
                    if b.get("schedules"):
                        b["meeting_title"] = b["schedules"].get("title")
                        b["duration_minutes"] = b["schedules"].get("duration")
                    results.append(b)

        results.sort(key=lambda x: x.get("scheduled_time", ""))
        return {"bookings": results}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bookings/{booking_id}")
async def get_booking(booking_id: str):
    try:
        booking = supabase.table("bookings").select(
            "*, schedules(title, duration, video_platform)"
        ).eq("id", booking_id).execute()
        if not booking.data:
            raise HTTPException(status_code=404, detail="Booking not found")
        b = booking.data[0]
        if b.get("schedules"):
            b["meeting_title"] = b["schedules"].get("title")
        return b
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/bookings/{booking_id}/confirm")
async def confirm_booking(booking_id: str):
    try:
        result = supabase.table("bookings").update({"status": "confirmed"}).eq("id", booking_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Booking not found")
        return {"success": True, "booking": result.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/bookings/{booking_id}/cancel")
async def cancel_booking(booking_id: str, body: Optional[BookingCancel] = None):
    try:
        booking = supabase.table("bookings").select("status").eq("id", booking_id).execute()
        if not booking.data:
            raise HTTPException(status_code=404, detail="Booking not found")
        if booking.data[0]["status"] == "cancelled":
            return {"success": True, "message": "Already cancelled"}
        result = supabase.table("bookings").update({"status": "cancelled"}).eq("id", booking_id).execute()
        return {"success": True, "booking": result.data[0] if result.data else {}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cancel error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/bookings/{booking_id}/complete")
async def complete_booking(booking_id: str):
    try:
        supabase.table("bookings").update({"status": "completed"}).eq("id", booking_id).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_stats(telegram_id: int):
    try:
        bookings = supabase.table("bookings").select("status, scheduled_time").eq(
            "organizer_telegram_id", telegram_id
        ).execute()
        now = datetime.now()
        total = len(bookings.data)
        upcoming = sum(
            1 for b in bookings.data
            if b["status"] in ("confirmed", "pending")
            and datetime.fromisoformat(b["scheduled_time"].replace("Z", "")) > now
        )
        completed = sum(1 for b in bookings.data if b["status"] == "completed")
        return {"total": total, "upcoming": upcoming, "completed": completed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

def _generate_meeting_link(platform: str, booking_id: str, schedule_id: str) -> str:
    short = booking_id.replace("-", "")[:10]
    sch_short = schedule_id.replace("-", "")[:6]
    links = {
        "jitsi":       f"https://meet.jit.si/sbapp-{sch_short}-{short[:8]}",
        "zoom":        f"https://zoom.us/j/{short}",
        "google_meet": f"https://meet.google.com/sbk-{sch_short[:3]}-{short[:4]}",
        "yandex":      f"https://telemost.yandex.ru/j/{short[:10]}",
        "mts":         f"https://meetings.mts.ru/{short[:10]}",
    }
    return links.get(platform, f"https://meet.jit.si/sbapp-{sch_short}-{short[:8]}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
