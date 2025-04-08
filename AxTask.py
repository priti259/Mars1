import requests
from config import config

robotId = "89824116043628m"

class Action:
    @staticmethod
    def PauseAction(duration):
        return {
            "type": 18,
            "data": {"pauseTime": duration},
        }

    @staticmethod
    def PlayAudioAction(audioId):
        return {
            "type": 5,
            "data": {
                "mode": 1,
                "url": "",
                "audioId": audioId,
                "interval": -1,
                "num": 1,
                "volume": 100,
                "channel": 1,
                "duration": -1,
            },
        }

class TaskPoint:
    def __init__(self, poi, ignoreYaw=True):
        self.pt = {
            "areaId": poi["areaId"],
            "x": poi["coordinate"][0],
            "y": poi["coordinate"][1],
            "type": 0,
            "stopRadius": 1,
            "ext": {"name": poi["name"]},
            "stepActs": []
        }
        if not ignoreYaw:
            self.pt["yaw"] = poi["yaw"]

    def addStepActs(self, stepAct):
        self.pt["stepActs"].append({**stepAct})
        return self

class TaskBuilder:
    def __init__(self, name: str, robotId: str):
        self.task = {
            "name": name,
            "robotId": robotId,
            "routeMode": 1,
            "runMode": 1,
            "runNum": 1,
            "taskType": 4,
            "runType": 21,
            "sourceType": 6,
            "ignorePublicSite": False,
            "speed": 1.0,
            "taskPts": []
        }

    def addTaskPt(self, tp):
        self.task["taskPts"].append({**tp.pt})
        return self

    def getTask(self):
        return self.task

class TaskManager:
    def __init__(self, token):
        self.token = token

    def newTask(self, taskData):
        url = config["URLPrefix"] + "/task/v1.1"
        try:
            r = requests.post(url, headers={"X-Token": self.token}, json=taskData, timeout=5)
            if r.status_code == 200:
                retData = r.json()
                if retData["status"] == 200:
                    return True, retData["data"]["taskId"]
        except requests.RequestException as e:
            print(e)
        return False, None

    def executeTask(self, taskId):
        url = config["URLPrefix"] + f"/task/v1.1/{taskId}/execute"
        try:
            r = requests.post(url, headers={"X-Token": self.token}, timeout=5)
            if r.status_code == 200:
                retData = r.json()
                if retData["status"] == 200:
                    return True
        except requests.RequestException as e:
            print(e)
        return False

# Simplified one-stop task function
def run_robot_task_to(poi):
    try:
        task = TaskBuilder("GoToPOI", robotId)
        tp = TaskPoint(poi)
        tp.addStepActs(Action.PlayAudioAction("3111002")) \
          .addStepActs(Action.PauseAction(5))
        task.addTaskPt(tp)

        manager = TaskManager(config["token"])
        ok, taskID = manager.newTask(task.getTask())
        if not ok:
            return False, "Failed to create task"

        ok = manager.executeTask(taskID)
        if not ok:
            return False, "Failed to execute task"

        return True, taskID

    except Exception as e:
        return False, f"Exception: {str(e)}"
