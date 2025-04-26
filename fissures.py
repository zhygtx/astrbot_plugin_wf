import requests  # 导入 requests 模块，用于发送 HTTP 请求
import json
from opencc import OpenCC
from datetime import datetime  # 导入 datetime 模块中的 datetime 类

platform = "pc"  # 设置平台参数，这里以 "pc" 为例
language = "zh"  # 设置语言参数，获取中文数据

# 构造 fissures 接口的 URL，包含路径参数和查询参数
url = f"https://api.warframestat.us/{platform}/fissures?language={language}"  # 拼接完整的 URL
response = requests.get(url)  # 发送 GET 请求获取 fissures 数据


def update_fissures_data():
    if response.status_code == 200:  # 若请求成功，状态码为 200
        fissures = response.json()  # 将响应的 JSON 数据解析为 Python 列表
        cc = OpenCC('t2s')  # 将繁体转换为简体，配置 't2s' （Traditional to Simplified）
        # 使用列表推导式筛选出还未过期的 fissure（expired 为 False 的记录）
        active_fissures = [f for f in fissures if not f.get("expired", False)]
        output_list = []  # 初始化一个空列表，用于存储每个 fissure 的关键信息
        # 获取当前 UTC 时间，并格式化为 ISO 8601 格式，其中 timespec='milliseconds' 表示保留毫秒部分
        now = datetime.utcnow().isoformat(timespec='milliseconds') + 'Z'
        # 遍历筛选后的 fissure 列表，输出每个 fissure 的关键信息
        for fissure in active_fissures:
            # 假设 fissure 中有 'node'、'missionType' 等字段需要转换
            node_traditional = fissure.get("node", "")
            mission_type_traditional = fissure.get("missionType", "")
            # 转换为简体中文
            node = cc.convert(node_traditional)  # 获取 fissure 所在的节点
            mission_type = cc.convert(mission_type_traditional)  # 获取任务类型
            ID = fissure.get("id")  # 获取此任务的ID
            tier = fissure.get("tier")  # 获取 fissure
            eta = fissure.get("eta")  # 获取剩余有效时间
            ishard = fissure.get("isHard")  # 是否为钢铁之路
            expiry = fissure.get("expiry")  # 节点的结束时间
            # 构建一本字典，每个字段均封装为带有 value 和 type 的结构
            output_line = {
                "ID": {"value": ID, "type": "id"},  # ID 标记为字符串类型
                "node": {"value": node, "type": "string"},  # 节点名称为字符串
                "missionType": {"value": mission_type, "type": "string"},  # 任务类型为字符串
                "tier": {"value": tier, "type": "string"},  # 缝隙类型为字符串
                "eta": {"value": eta, "type": "time"},  # 剩余时间被标记为时间类型
                "isHard": {"value": ishard, "type": "boolean"},  # 是否为钢铁之路为布尔类型
                "expiry": {"value": expiry, "type": "time"},  # 标记节点的结束时间
                "now": {"value": now, "type": "time"}
            }
            # 将当前记录添加到列表中
            output_list.append(output_line)
            # 将收集到的数据写入到一个 JSON 文件中
        with open("fissures.json", "w", encoding="utf-8") as f:
            # 使用 json.dump() 写入数据，indent=4 实现美化格式，ensure_ascii=False 保证中文不被转义
            json.dump(output_list, f, ensure_ascii=False, indent=4)
        print("数据已成功记录到文件中。")
    else:
        # 如果请求失败，则打印出错误状态码
        print(f"请求失败，状态码: {response.status_code}")


async def run_fissures_module():
    #文件的主函数，用于统合整个模块功能，
    await update_fissures_data()
    #加载JSON文件数据
    with open("fissures.json", "r", encoding="utf-8") as f:
        data = json.load(f)  # 加载整个 JSON 文件为 Python 对象（通常为列表）
    min_time = min(
        data,
        key=lambda record: datetime.fromisoformat(record['expiry']['value'].replace("Z", "+00:00"))
    )

    # 这里可以继续执行其他逻辑，比如异步发送结果到聊天机器人后台
    return min_time
