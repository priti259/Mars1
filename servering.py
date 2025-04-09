from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import asyncio
import nest_asyncio
import math
import requests
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
last_task_id = None
running = False
queue_lock = asyncio.Lock()
robot_manager = RobotManager(config["token"])
password_waiting = {}  # chat_id: (poi, user_name)

# Location-based Notifications
ALMOST_THERE_DISTANCE = 5.0
ARRIVAL_TOLERANCE = 0.5
notification_sent = {'departed': False, 'almost_there': False, 'arrived': False}

def reset_notification_flags():
    global notification_sent
    notification_sent = {'departed': False, 'almost_there': False, 'arrived': False}

# POI list
POI_LIST = [
    {"name": "4D Robot", "coordinate": [-3.35, 7.97], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Cafeteria", "coordinate": [20.46, 1.41], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Charging Station", "coordinate": [-4.63, 3.73], "yaw": 355.11, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Cupboard", "coordinate": [-1.12, 1.01], "yaw": 3.71, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Door", "coordinate": [-0.61, 1.66], "yaw": 2.54, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Entrance", "coordinate": [20.11, 68.40], "yaw": 86.84, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Founder cabin", "coordinate": [19.14, 28.95], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Founder lounge", "coordinate": [19.19, 40.19], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "HR", "coordinate": [19.64, 57.38], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "MB SHUTTLE", "coordinate": [4.78, 30.48], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "NPD", "coordinate": [18.08, 11.06], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Play area", "coordinate": [15.73, 6.77], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "Reception", "coordinate": [19.89, 65.67], "yaw": 355.02, "areaId": "67f4a016dd20bc984408fd60"},
    {"name": "VR", "coordinate": [18.62, 45.14], "yaw": 0, "areaId": "67f4a016dd20bc984408fd60"},
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

def remove_task(task_id):
    url = config["URLPrefix"] + "/task/v1.1/removeTask"
    headers = {
        "X-Token": config["token"],
        "Content-Type": "application/json"
    }
    payload = {"taskId": task_id}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=5)
        if response.status_code == 200:
            res = response.json()
            return res.get("status") == 200, res.get("message", "")
    except Exception as e:
        print("[Remove Task Error]", e)
    return False, "Failed to remove task"

async def cancel_task_via_api(update: Update):
    global last_task_id
    if last_task_id:
        success, msg = remove_task(last_task_id)
        await update.message.reply_text("✅ Task removed via API." if success else f"❌ Failed to cancel task: {msg}")
    else:
        await update.message.reply_text("⚠️ No task ID available to cancel.")
