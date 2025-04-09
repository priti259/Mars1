import asyncio
import nest_asyncio
import math
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from AxTask import run_robot_task_to
from AxRobot import RobotManager
import logging
from collections import deque

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_TOKEN = "8143266327:AAGSoF0-9DeBtCybVaIhGpLsQH6JyjVxmmg"
PRIORITY_PASSWORD = "robotmaster123"  # For priority queue access
CANCEL_PASSWORD = "cancelall"  # Command to clear queue
DEFAULT_ROBOT_ID = "89824116043628m"

# Global state
task_queue = deque()
current_task = None
running = False
queue_lock = asyncio.Lock()
robot_manager = RobotManager(config["token"])
password_waiting = {}  # chat_id: (poi, user_name)
task_history = []
MAX_HISTORY = 50

# Notification thresholds
ALMOST_THERE_DISTANCE = 5.0
ARRIVAL_TOLERANCE = 0.5

class TaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class RobotTask:
    def __init__(self, user, poi, chat_id):
        self.user = user
        self.poi = poi
        self.chat_id = chat_id
        self.status = TaskStatus.PENDING
        self.start_time = None
        self.end_time = None
        self.task_id = f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}_{hash(poi['name'])}"
    
    def start(self):
        self.status = TaskStatus.RUNNING
        self.start_time = datetime.now()
    
    def complete(self):
        self.status = TaskStatus.COMPLETED
        self.end_time = datetime.now()
    
    def fail(self):
        self.status = TaskStatus.FAILED
        self.end_time = datetime.now()
    
    def cancel(self):
        self.status = TaskStatus.CANCELLED
        self.end_time = datetime.now()
    
    def duration(self):
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0
    
    def to_dict(self):
        return {
            "task_id": self.task_id,
            "user": self.user,
            "poi": self.poi['name'],
            "status": self.status,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration": self.duration(),
            "chat_id": self.chat_id
        }

# POI Configuration
POI_LIST = [
    {"name": "4D Robot", "coordinate": [-3.35, 7.97], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    # ... (other POIs from original code)
]
POI_MAP = {poi["name"].lower().replace(" ", "_"): poi for poi in POI_LIST}

def reset_notification_flags():
    return {'departed': False, 'almost_there': False, 'arrived': False}

notification_sent = reset_notification_flags()

# Robot Control Functions
def robot_is_busy():
    success, data = robot_manager.getRobotState(DEFAULT_ROBOT_ID)
    if success:
        return data.get("speed", 0) > 0.01 or data.get("isEmergencyStop") or bool(data.get("errors"))
    return False

def robot_reached_destination(target_poi, tolerance=0.5):
    success, data = robot_manager.getRobotState(DEFAULT_ROBOT_ID)
    if success:
        rx, ry = data.get("x"), data.get("y")
        tx, ty = target_poi["coordinate"]
        return rx is not None and ry is not None and math.hypot(rx - tx, ry - ty) <= tolerance
    return False

async def check_location_and_notify(poi, chat_id):
    success, data = robot_manager.getRobotState(DEFAULT_ROBOT_ID)
    if not success:
        return
    
    rx, ry = data.get("x"), data.get("y")
    tx, ty = poi["coordinate"]
    distance = math.hypot(rx - tx, ry - ty)
    speed = data.get("speed", 0)

    if speed > 0.1 and not notification_sent['departed']:
        await app.bot.send_message(chat_id, "🚀 Robot has departed.")
        notification_sent['departed'] = True
    elif distance <= ALMOST_THERE_DISTANCE and not notification_sent['almost_there']:
        await app.bot.send_message(chat_id, "🛵 Almost there!")
        notification_sent['almost_there'] = True
    elif distance <= ARRIVAL_TOLERANCE and speed < 0.1 and not notification_sent['arrived']:
        await app.bot.send_message(chat_id, f"📍 Arrived at {poi['name']}!")
        reset_notification_flags()

# Task Management
def add_task_to_history(task):
    task_history.append(task.to_dict())
    if len(task_history) > MAX_HISTORY:
        task_history.pop(0)

async def show_task_details(update: Update, task_id: str = None):
    if task_id:
        task = next((t for t in task_history if t['task_id'] == task_id), None)
        if task:
            message = (
                f"📋 Task Details:\nID: {task['task_id']}\n"
                f"Destination: {task['poi']}\nStatus: {task['status'].upper()}\n"
                f"Requested by: {task['user']}\nStart: {task['start_time']}\n"
                f"End: {task['end_time']}\nDuration: {task['duration']:.1f}s"
            )
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("❌ Task not found")
    else:
        if current_task:
            await update.message.reply_text(
                f"🔍 Current Task:\nID: {current_task.task_id}\n"
                f"Destination: {current_task.poi['name']}\n"
                f"Status: {current_task.status.upper()}\n"
                f"Requested by: {current_task.user}"
            )
        else:
            await update.message.reply_text("ℹ️ No active task")

async def show_task_history(update: Update, limit: int = 5):
    if not task_history:
        await update.message.reply_text("ℹ️ No task history available")
        return
    
    message = "📜 Task History:\n"
    for i, task in enumerate(reversed(task_history[-limit:]), 1):
        message += (
            f"{i}. {task['poi']} - {task['status'].upper()} "
            f"(by {task['user']}, {task['duration']:.1f}s)\n"
        )
    await update.message.reply_text(message)

async def show_queued_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not task_queue:
        await update.message.reply_text("ℹ️ No tasks in queue")
        return
    
    message = "📃 Task Queue:\n"
    for i, task in enumerate(task_queue, 1):
        message += (
            f"{i}. {task.poi['name']} - {task.status.upper()} "
            f"(by {task.user}, ID: {task.task_id[:8]}...)\n"
        )
    
    if current_task:
        message += f"\n🔧 Current Task: {current_task.poi['name']} (by {current_task.user})"
    
    await update.message.reply_text(message)

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Welcome to Robot Control Bot!\n"
        "Type /help for commands\n"
        "Press / to see command menu"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 Robot Control Bot - Available Commands:

/menu - Show destination menu
/stop - Emergency stop (available to all)
/tasks - Show task queue
/status - Check task status
/history - View task history
/help - Show this message

🔧 Available to all:
- Type 'cancelall' to clear all tasks
- Use /stop for emergency stop
"""
    await update.message.reply_text(help_text)

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [InlineKeyboardButton(poi["name"], callback_data=key) for key, poi in POI_MAP.items()]
    keyboard = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    await update.message.reply_text(
        "📍 Choose a destination:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    poi = POI_MAP[query.data]
    chat_id = query.message.chat_id or user.id

    async with queue_lock:
        if running:
            password_waiting[chat_id] = (poi, user.full_name)
            await query.message.reply_text(
                "🔒 Robot is busy. Send priority password or type 'cancelall' to clear queue."
            )
            return
        
        task = RobotTask(user.full_name, poi, chat_id)
        task_queue.append(task)
        await query.edit_message_text(
            f"📦 Task queued (ID: {task.task_id})\n"
            f"Position: #{len(task_queue)}\n"
            f"Destination: {poi['name']}"
        )

async def emergency_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global running, current_task
    
    if not robot_is_busy() and not running:
        await update.message.reply_text("🤖 Robot not moving.")
        return
    
    success, _ = robot_manager.emergencyStop(DEFAULT_ROBOT_ID)
    if success:
        async with queue_lock:
            task_queue.clear()
            if current_task:
                current_task.cancel()
                add_task_to_history(current_task)
            running = False
            current_task = None
        
        await update.message.reply_text("🛑 Emergency stop activated! Queue cleared.")
    else:
        await update.message.reply_text("❌ Emergency stop failed. Try again or contact support.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global running, current_task
    chat_id = update.effective_chat.id
    msg = update.message.text.strip()
    
    # Handle cancelall command (available to all users)
    if msg.lower() == CANCEL_PASSWORD.lower():
        async with queue_lock:
            task_queue.clear()
            if current_task:
                current_task.cancel()
                add_task_to_history(current_task)
            running = False
            current_task = None
        await update.message.reply_text("🧹 All tasks cleared!")
        return
    
    # Handle priority requests
    if chat_id in password_waiting:
        poi, user = password_waiting.pop(chat_id)
        
        if msg == PRIORITY_PASSWORD:
            async with queue_lock:
                task = RobotTask(user, poi, chat_id)
                task_queue.appendleft(task)
            await update.message.reply_text("✅ Priority task queued!")
        else:
            async with queue_lock:
                task = RobotTask(user, poi, chat_id)
                task_queue.append(task)
            await update.message.reply_text("📦 Task added to queue")
    else:
        await update.message.reply_text(
            "💡 Use /menu to select destination\n"
            "🛑 Type 'cancelall' to clear all tasks\n"
            "🚨 Use /stop for emergency stop"
        )

# Task Worker
async def task_worker():
    global running, current_task
    
    while True:
        await asyncio.sleep(1)
        
        if not running and task_queue and not robot_is_busy():
            async with queue_lock:
                current_task = task_queue.popleft()
                current_task.start()
                running = True
                reset_notification_flags()
            
            chat_id = current_task.chat_id
            poi = current_task.poi
            
            try:
                await app.bot.send_message(
                    chat_id,
                    f"🚀 Starting task {current_task.task_id}\n"
                    f"Destination: {poi['name']}"
                )
                
                success, _ = run_robot_task_to(poi)
                if not success:
                    raise Exception("Failed to start navigation")
                
                while not robot_reached_destination(poi):
                    await check_location_and_notify(poi, chat_id)
                    await asyncio.sleep(2)
                
                current_task.complete()
                add_task_to_history(current_task)
                
                await app.bot.send_message(
                    chat_id,
                    f"✅ Task completed!\n"
                    f"Destination: {poi['name']}\n"
                    f"Duration: {current_task.duration():.1f} seconds"
                )
                
            except Exception as e:
                current_task.fail()
                add_task_to_history(current_task)
                await app.bot.send_message(
                    chat_id,
                    f"❌ Task failed: {str(e)}\n"
                    f"We'll try the next task in queue"
                )
                logger.error(f"Task failed: {str(e)}")
            
            finally:
                running = False
                current_task = None

# Bot Setup
async def post_init(application):
    commands = [
        BotCommand("menu", "Show destination menu"),
        BotCommand("stop", "Emergency stop the robot"),
        BotCommand("tasks", "Show task queue"),
        BotCommand("status", "Check task status"),
        BotCommand("history", "View task history"),
        BotCommand("help", "Show all commands"),
        BotCommand("start", "Welcome message")
    ]
    await application.bot.set_my_commands(commands)

async def run_bot():
    global app
    
    app = ApplicationBuilder() \
        .token(TELEGRAM_TOKEN) \
        .post_init(post_init) \
        .build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("menu", show_menu))
    app.add_handler(CommandHandler("stop", emergency_stop))
    app.add_handler(CommandHandler("status", task_status))
    app.add_handler(CommandHandler("history", task_history_handler))
    app.add_handler(CommandHandler("tasks", show_queued_tasks))
    
    # Other handlers
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start task worker
    asyncio.create_task(task_worker())
    
    # Start bot
    await app.run_polling()

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(run_bot())
