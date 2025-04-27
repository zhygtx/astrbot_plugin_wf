# update_json.py
import os
import requests
import json
from opencc import OpenCC
from datetime import datetime


def update_fissures():
    platform = "pc"
    language = "zh"
    url = f"https://api.warframestat.us/{platform}/fissures?language={language}"
    response = requests.get(url)

    if response.status_code == 200:
        fissures = response.json()
        cc = OpenCC('t2s')
        # 筛选出尚未过期的 fissure
        active_fissures = [f for f in fissures if not f.get("expired", False)]
        output_list = []
        now = datetime.utcnow().isoformat(timespec='milliseconds') + 'Z'
        for fissure in active_fissures:
            node_traditional = fissure.get("node", "")
            mission_type_traditional = fissure.get("missionType", "")
            node = cc.convert(node_traditional)
            mission_type = cc.convert(mission_type_traditional)
            ID = fissure.get("id")
            tier = fissure.get("tier")
            eta = fissure.get("eta")
            ishard = fissure.get("isHard")
            expiry = fissure.get("expiry")
            output_line = {
                "ID": {"value": ID, "type": "id"},
                "node": {"value": node, "type": "string"},
                "missionType": {"value": mission_type, "type": "string"},
                "tier": {"value": tier, "type": "string"},
                "eta": {"value": eta, "type": "time"},
                "isHard": {"value": ishard, "type": "boolean"},
                "expiry": {"value": expiry, "type": "time"},
                "now": {"value": now, "type": "time"}
            }
            output_list.append(output_line)
        # 使用绝对路径确保 JSON 文件写入在当前脚本所在目录
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fissures.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(output_list, f, ensure_ascii=False, indent=4)
        print("fissures.json 更新成功")
    else:
        print(f"请求失败，状态码: {response.status_code}")


if __name__ == "__main__":
    update_fissures()
