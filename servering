from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import asyncio
import nest_asyncio
import math
import time  # for potential timeout or debug purposes
from AxTask import run_robot_task_to
from AxRobot import RobotManager
from config import config
import requests

TELEGRAM_TOKEN = "8143266327:AAGSoF0-9DeBtCybVaIhGpLsQH6JyjVxmmg"
PRIORITY_PASSWORD = "robotmaster123"
ROBOT_ID = "89824116043628m"

task_queue = []
current_task = None
running = False
queue_lock = asyncio.Lock()
robot_manager = RobotManager(config["token"])
password_waiting = {}  # chat_id: (poi, user_name)

# === Location-based Notification Constants ===
ALMOST_THERE_DISTANCE = 5.0  # meters
ARRIVAL_TOLERANCE = 0.5      # meters

# === Notification State ===
notification_sent = {
    'departed': False,
    'almost_there': False,
    'arrived': False
}

def reset_notification_flags():
    global notification_sent
    notification_sent = {
        'departed': False,
        'almost_there': False,
        'arrived': False
    }

# === Full POI List ===
POI_LIST = [
    {"name": "4D Robot", "coordinate": [-3.346762595697328, 7.966625742028555], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Cafeteria", "coordinate": [20.45789549043775, 1.408879006277175], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Charging Station", "coordinate": [-4.631621854105097, 3.732192876067057], "yaw": 355.11, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Cupboard", "coordinate": [-1.12, 1.005], "yaw": 3.71, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Door", "coordinate": [-0.61, 1.66], "yaw": 2.54, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Entrance", "coordinate": [20.10689870672877, 68.39641959672349], "yaw": 86.84, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Founder cabin", "coordinate": [19.13888285713483, 28.94657439426851], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Founder lounge", "coordinate": [19.185244625816722, 40.18561394914855], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "HR", "coordinate": [19.64477593077163, 57.37553110250815], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "MB SHUTTLE", "coordinate": [4.783901275402513, 30.47702397111607], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "NPD", "coordinate": [18.080248328544712, 11.064889080216744], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Play area", "coordinate": [15.734488147245429, 6.771066552886396], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Reception", "coordinate": [19.894923514982565, 65.67319059215038], "yaw": 355.02, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "VR", "coordinate": [18.62183095425962, 45.13760268693545], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
]

POI_MAP = {
    poi["name"].lower().replace(" ", "_"): poi for poi in POI_LIST
}

def robot_is_busy():
    success, data = robot_manager.getRobotState(ROBOT_ID)
    if success:
        print("[Robot Status]", data)
        is_moving = data.get("speed", 0) > 0.01
        has_error = data.get("isEmergencyStop") or bool(data.get("errors"))
        return is_moving or has_error
    print("[Robot Status] Failed to retrieve status.")
    return False

def robot_reached_destination(target_poi, tolerance=0.5):
    success, data = robot_manager.getRobotState(ROBOT_ID)
    if success:
        robot_x = data.get("x")
        robot_y = data.get("y")
        if robot_x is None or robot_y is None:
            return False

        target_x, target_y = target_poi["coordinate"]
        distance = math.hypot(robot_x - target_x, robot_y - target_y)
        print(f"[Robot Check] Distance to target: {distance:.2f}")
        return distance <= tolerance
    return False

async def check_location_and_notify(poi, chat_id):
    global notification_sent
    success, data = robot_manager.getRobotState(ROBOT_ID)
    if not success:
        print("[Notify] Failed to get robot state.")
        return

    robot_x = data.get("x")
    robot_y = data.get("y")
    target_x, target_y = poi["coordinate"]
    distance = math.hypot(robot_x - target_x, robot_y - target_y)
    current_speed = data.get("speed", 0)
    print(f"[Notify] Distance: {distance:.2f} m, Speed: {current_speed:.2f}")

    # Check if robot has departed
    if current_speed > 0.1 and not notification_sent['departed']:
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text="🚀 Out for delivery! Robot has departed."
            )
            print("[Notify] 'departed' message sent.")
        except Exception as e:
            print("[Error] Failed to send 'departed' message:", e)
        notification_sent['departed'] = True
        notification_sent['almost_there'] = False
        notification_sent['arrived'] = False

    # Check if robot is approaching destination
    if distance <= ALMOST_THERE_DISTANCE and not notification_sent['almost_there'] and notification_sent['departed']:
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text="🛵 Almost there! Robot is within 5 meters of destination."
            )
            print("[Notify] 'almost there' message sent.")
        except Exception as e:
            print("[Error] Failed to send 'almost there' message:", e)
        notification_sent['almost_there'] = True

    # Check if robot has arrived
    if distance <= ARRIVAL_TOLERANCE and current_speed < 0.1 and not notification_sent['arrived']:
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=f"📍 Arrived at {poi['name']}! Robot is at location."
            )
            print("[Notify] 'arrived' message sent.")
        except Exception as e:
            print("[Error] Failed to send 'arrived' message:", e)
        notification_sent['arrived'] = True
        reset_notification_flags()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("Hi! 👋 Use /menu to choose a destination for the robot.")
    except Exception as e:
        print("[Error] In start:", e)

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(poi["name"], callback_data=key)]
        for key, poi in POI_MAP.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await update.message.reply_text("📍 Choose a destination:", reply_markup=reply_markup)
    except Exception as e:
        print("[Error] In show_menu:", e)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    selected_key = query.data
    poi = POI_MAP[selected_key]

    async with queue_lock:
        if running:
            password_waiting[query.message.chat_id] = (poi, user.full_name)
            try:
                await query.message.reply_text("🔒 Robot is busy. Send priority password as your next message to override the queue.")
            except Exception as e:
                print("[Error] In button_handler (robot busy):", e)
            return

        task = {"user": user.full_name, "poi": poi, "chat_id": query.message.chat_id}
        task_queue.append(task)
        position = len(task_queue)
        try:
            await query.edit_message_text(text=f"📦 Task added to queue at position #{position}. Waiting for execution...")
        except Exception as e:
            print("[Error] In button_handler (edit_message):", e)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text.strip()

    if chat_id in password_waiting:
        poi, user_name = password_waiting.pop(chat_id)
        if text == PRIORITY_PASSWORD:
            task = {"user": user_name, "poi": poi, "chat_id": chat_id}
            async with queue_lock:
                task_queue.insert(0, task)
            try:
                await update.message.reply_text("✅ Priority override accepted. Task moved to front of queue.")
            except Exception as e:
                print("[Error] In handle_message (priority override):", e)
        else:
            try:
                await update.message.reply_text("❌ Incorrect password. Task will remain in regular queue.")
            except Exception as e:
                print("[Error] In handle_message (incorrect password):", e)
            async with queue_lock:
                task_queue.append({"user": user_name, "poi": poi, "chat_id": chat_id})
    else:
        try:
            await update.message.reply_text("💡 Use /menu to select a destination from buttons.")
        except Exception as e:
            print("[Error] In handle_message (default):", e)

async def emergency_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global running, current_task

    # Check if robot is actually moving
    if not robot_is_busy() and not running:
        try:
            await update.message.reply_text("🤖 Robot is not currently moving.")
        except Exception as e:
            print("[Error] In emergency_stop (not moving):", e)
        return

    # Send emergency stop command with retries
    max_retries = 3
    for attempt in range(max_retries):
        success, response = robot_manager.emergencyStop(ROBOT_ID)

        if success:
            await asyncio.sleep(1)  # Give robot time to react
            if robot_is_busy():
                try:
                    await update.message.reply_text("⚠️ Stop command sent but robot still moving. Retrying...")
                except Exception as e:
                    print("[Error] In emergency_stop (retry message):", e)
                continue

            async with queue_lock:
                running = False
                if current_task:
                    try:
                        await context.bot.send_message(
                            chat_id=current_task["chat_id"],
                            text=f"🛑 EMERGENCY STOP: Task to {current_task['poi']['name']} was interrupted!"
                        )
                    except Exception as e:
                        print("[Error] In emergency_stop (current_task message):", e)
                    current_task = None

                for task in task_queue:
                    try:
                        await context.bot.send_message(
                            chat_id=task["chat_id"],
                            text=f"🚨 Queued task to {task['poi']['name']} was cancelled due to emergency stop."
                        )
                    except Exception as e:
                        print("[Error] In emergency_stop (task queue message):", e)
                task_queue.clear()

                for chat_id in list(password_waiting.keys()):
                    password_waiting.pop(chat_id)

            success, status = robot_manager.getRobotState(ROBOT_ID)
            status_msg = (f"✅ Emergency stop successful!\n"
                          f"📍 Current position: x={status.get('x', '?')}, y={status.get('y', '?')}\n"
                          f"⚡ Battery: {status.get('battery', '?')}%\n"
                          f"🚦 Status: {'STOPPED' if not status.get('isEmergencyStop', True) else 'EMERGENCY_STOP'}")
            try:
                await update.message.reply_text(status_msg)
            except Exception as e:
                print("[Error] In emergency_stop (final status message):", e)
            return

    try:
        await update.message.reply_text("❌ EMERGENCY STOP FAILED after 3 attempts! Please check robot physically.")
    except Exception as e:
        print("[Error] In emergency_stop (failure message):", e)

async def task_worker():
    global running, current_task
    while True:
        await asyncio.sleep(1)
        print("[Worker] Tick | Running:", running, "| Queue:", len(task_queue), "| Busy:", robot_is_busy())

        if not running and task_queue and not robot_is_busy():
            async with queue_lock:
                current_task = task_queue.pop(0)
                running = True
                reset_notification_flags()

            chat_id = current_task["chat_id"]
            user = current_task["user"]
            poi = current_task["poi"]

            print(f"🔧 Running task for {user}: {poi['name']}")
            success, result = run_robot_task_to(poi)

            if not success:
                try:
                    await app.bot.send_message(chat_id=chat_id, text=f"❌ Task to {poi['name']} failed: {result}")
                except Exception as e:
                    print("[Error] In task_worker (task failure message):", e)
                running = False
                current_task = None
                continue

            while not robot_reached_destination(poi):
                await check_location_and_notify(poi, chat_id)
                await asyncio.sleep(2)
                print(f"⏳ Waiting for robot to reach {poi['name']}...")

            await check_location_and_notify(poi, chat_id)
            await asyncio.sleep(10)
            try:
                await app.bot.send_message(chat_id=chat_id, text=f"✅ Task to {poi['name']} completed!")
            except Exception as e:
                print("[Error] In task_worker (completion message):", e)
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

    print("🤖 Telegram bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(run_bot())
