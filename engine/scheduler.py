import json
import re
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AITask, AIRoutine
from database.migrations import async_session_factory
from server.config import settings

scheduler = AsyncIOScheduler()


async def execute_task(task_id: int, db: Optional[AsyncSession] = None):
    if not db:
        async with async_session_factory() as session:
            await _execute_task_internal(task_id, session)
    else:
        await _execute_task_internal(task_id, db)


async def _execute_task_internal(task_id: int, db: AsyncSession):
    result = await db.execute(select(AITask).where(AITask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        return

    task.status = 'running'
    await db.commit()

    try:
        if task.task_type == 'reminder':
            result_msg = await execute_reminder(task)
        elif task.task_type == 'key_upload':
            result_msg = await execute_key_upload(task)
        elif task.task_type == 'report':
            result_msg = await execute_report(task)
        elif task.task_type == 'cleanup':
            result_msg = await execute_cleanup(task)
        else:
            result_msg = await execute_custom(task)

        task.status = 'completed'
        task.result = result_msg
        task.executed_at = datetime.utcnow()
        await db.commit()

        await db.execute(delete(AITask).where(AITask.id == task_id))
        await db.commit()
    except Exception as e:
        task.status = 'failed'
        task.result = str(e)
        task.executed_at = datetime.utcnow()
        await db.commit()


async def execute_routine(routine_id: int):
    async with async_session_factory() as db:
        result = await db.execute(select(AIRoutine).where(AIRoutine.id == routine_id))
        routine = result.scalar_one_or_none()
        if not routine or not routine.is_active:
            return

        try:
            if routine.task_type == 'reminder':
                msg = await execute_reminder_from_data(routine.data)
            elif routine.task_type == 'key_upload':
                msg = await execute_key_upload_from_data(routine.data)
            elif routine.task_type == 'report':
                msg = await execute_report_from_data(routine.data)
            else:
                msg = await execute_custom_from_data(routine.data)

            routine.last_run = datetime.utcnow()
            await db.commit()
        except Exception as e:
            routine.last_run = datetime.utcnow()
            await db.commit()


async def execute_reminder(task: AITask) -> str:
    return json.dumps({"message": "Reminder triggered", "data": task.data})


async def execute_key_upload(task: AITask) -> str:
    return json.dumps({"message": "Key upload triggered", "data": task.data})


async def execute_report(task: AITask) -> str:
    return json.dumps({"message": "Report generated", "data": task.data})


async def execute_cleanup(task: AITask) -> str:
    return json.dumps({"message": "Cleanup completed", "data": task.data})


async def execute_custom(task: AITask) -> str:
    return json.dumps({"message": "Custom task executed", "data": task.data})


async def execute_reminder_from_data(data: dict) -> str:
    return json.dumps({"message": "Routine reminder triggered", "data": data})


async def execute_key_upload_from_data(data: dict) -> str:
    return json.dumps({"message": "Routine key upload triggered", "data": data})


async def execute_report_from_data(data: dict) -> str:
    return json.dumps({"message": "Routine report generated", "data": data})


async def execute_custom_from_data(data: dict) -> str:
    return json.dumps({"message": "Routine custom task executed", "data": data})


@scheduler.scheduled_job('interval', minutes=1)
async def check_pending_tasks():
    async with async_session_factory() as db:
        now = datetime.utcnow()
        result = await db.execute(
            select(AITask).where(
                AITask.status == 'pending',
                AITask.scheduled_at <= now,
            )
        )
        tasks = result.scalars().all()
        for task in tasks:
            scheduler.add_job(
                execute_task,
                trigger=DateTrigger(datetime.utcnow()),
                args=[task.id],
                id=f"task_{task.id}",
                replace_existing=True,
            )


async def load_routines():
    async with async_session_factory() as db:
        result = await db.execute(
            select(AIRoutine).where(AIRoutine.is_active == True)
        )
        routines = result.scalars().all()
        for routine in routines:
            add_routine_job(routine)


def add_routine_job(routine: AIRoutine):
    trigger = CronTrigger.from_crontab(routine.cron_expression)
    scheduler.add_job(
        execute_routine,
        trigger=trigger,
        args=[routine.id],
        id=f"routine_{routine.id}",
        replace_existing=True,
        next_run_time=routine.next_run or datetime.utcnow(),
    )


def remove_routine_job(routine_id: int):
    try:
        scheduler.remove_job(f"routine_{routine_id}")
    except Exception:
        pass


def extract_task_action(text: str) -> Optional[dict]:
    json_match = re.search(r'\{.*?"action".*?\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            pass
    return None
