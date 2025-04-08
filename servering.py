from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import asyncio
import nest_asyncio
import math
from AxTask import run_robot_task_to
from AxRobot import RobotManager
from config import config

TELEGRAM_TOKEN = "8143266327:AAGSoF0-9DeBtCybVaIhGpLsQH6JyjVxmmg"
PRIORITY_PASSWORD = "robotmaster123"
CANCEL_PASSWORD = "cancelall"
ROBOT_ID = "89824116043628m"

# Globals
task_queue = []
current_task = None
running = False
queue_lock = asyncio.Lock()
robot_manager = RobotManager(config["token"])
password_waiting = {}  # chat_id: (poi, user_name)
cancel_waiting = set()

# Location-based Notifications
ALMOST_THERE_DISTANCE = 5.0
ARRIVAL_TOLERANCE = 0.5
notification_sent = {'departed': False, 'almost_there': False, 'arrived': False}

def reset_notification_flags():
    global notification_sent
    notification_sent = {'departed': False, 'almost_there': False, 'arrived': False}

# POI list
POI_LIST = [
    {"name": "Cupboard", "coordinate": [-1.12, 1.005], "yaw": 3.71, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Door", "coordinate": [-0.61, 1.66], "yaw": 2.54, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Charging Station", "coordinate": [-4.6316, 3.7321], "yaw": 355.11, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Reception", "coordinate": [19.89, 65.67], "yaw": 355.02, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Play area", "coordinate": [15.73, 6.77], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "VR", "coordinate": [18.62, 45.13], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"}
]
POI_MAP = {poi["name"].lower().replace(" ", "_"): poi for poi in POI_LIST}

def robot_is_busy():
    success, data = robot_manager.getRobotState(ROBOT_ID)
    if success:
        return data.get("speed", 0) > 0.01 or data.get("isEmergencyStop") or bool(data.get("errors"))
    return False

def robot_reached_destination(target_poi, tolerance=0.5):
    success, data = robot_manager.getRobotState(ROBOT_ID)
    if success:
        rx, ry = data.get("x"), data.get("y")
        tx, ty = target_poi["coordinate"]
        return rx is not None and ry is not None and math.hypot(rx - tx, ry - ty) <= tolerance
    return False

async def check_location_and_notify(poi, chat_id):
    success, data = robot_manager.getRobotState(ROBOT_ID)
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hi! 👋 Use /menu to choose a destination for the robot.")

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [InlineKeyboardButton(poi["name"], callback_data=key) for key, poi in POI_MAP.items()]
    keyboard = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    await update.message.reply_text("📍 Choose a destination:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    poi = POI_MAP[query.data]

    async with queue_lock:
        if running:
            password_waiting[query.message.chat_id] = (poi, user.full_name)
            await query.message.reply_text("🔒 Robot is busy. Send priority password or type 'cancelall' to clear queue.")
            return
        task_queue.append({"user": user.full_name, "poi": poi, "chat_id": query.message.chat_id})
        await query.edit_message_text(f"📦 Task queued. Position: #{len(task_queue)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global running, current_task
    chat_id = update.message.chat_id
    msg = update.message.text.strip()

    if chat_id in password_waiting:
        poi, user = password_waiting.pop(chat_id)
        if msg == PRIORITY_PASSWORD:
            async with queue_lock:
                task_queue.insert(0, {"user": user, "poi": poi, "chat_id": chat_id})
            await update.message.reply_text("✅ Task moved to front of queue.")
        else:
            async with queue_lock:
                task_queue.append({"user": user, "poi": poi, "chat_id": chat_id})
            await update.message.reply_text("❌ Wrong password. Task added to end of queue.")

    elif msg.strip().lower() == CANCEL_PASSWORD:
        async with queue_lock:
            task_queue.clear()
            running = False
            current_task = None
        await update.message.reply_text("🧹 All tasks cleared by admin password.")
    else:
        await update.message.reply_text("💡 Use /menu to select a destination.")

async def emergency_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global running, current_task
    if not robot_is_busy() and not running:
        await update.message.reply_text("🤖 Robot not moving.")
        return

    success, _ = robot_manager.emergencyStop(ROBOT_ID)
    if success:
        async with queue_lock:
            task_queue.clear()
            running = False
            current_task = None
        await update.message.reply_text("🛑 Emergency stop sent and queue cleared.")
    else:
        await update.message.reply_text("❌ Emergency stop failed.")

async def task_worker():
    global running, current_task
    while True:
        await asyncio.sleep(1)
        if not running and task_queue and not robot_is_busy():
            async with queue_lock:
                current_task = task_queue.pop(0)
                running = True
                reset_notification_flags()

            chat_id = current_task["chat_id"]
            poi = current_task["poi"]
            success, _ = run_robot_task_to(poi)
            if not success:
                await app.bot.send_message(chat_id, f"❌ Failed to start task to {poi['name']}")
                running = False
                continue

            while not robot_reached_destination(poi):
                await check_location_and_notify(poi, chat_id)
                await asyncio.sleep(2)

            await check_location_and_notify(poi, chat_id)
            await asyncio.sleep(10)
            await app.bot.send_message(chat_id, f"✅ Reached {poi['name']}!")
            running = False
            current_task = None

async def run_bot():
    global app
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", show_menu))
    app.add_handler(CommandHandler("stop", emergency_stop))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    asyncio.create_task(task_worker())
    await app.run_polling()

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(run_bot())
