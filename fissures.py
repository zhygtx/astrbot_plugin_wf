import asyncio
import os
import requests  # 导入 requests 模块，用于发送 HTTP 请求
import json
from opencc import OpenCC
from datetime import datetime  # 导入 datetime 模块中的 datetime 类


async def run_update_process():
    # 获取当前文件所在目录的绝对路径并构造 update_json.py 的绝对路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    update_script = os.path.join(current_dir, "update_json.py")

    # 启动子进程时不捕获输出（使用 DEVNULL）
    process = await asyncio.create_subprocess_exec(
        "python", update_script,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    await process.communicate()


async def run_fissures_module() -> str:
    # 先调用外部程序更新 JSON 数据，此调用不关心返回内容
    await run_update_process()
    # 确保程序能定位到 fissures.json 文件所在的位置
    # os.path.abspath(__file__) 获取当前脚本的完整路径，
    # os.path.dirname() 获取这个路径所在的目录
    current_dir = os.path.dirname(os.path.abspath(__file__))  # 当前脚本所在目录
    # 构造 fissures.json 文件的完整路径：保证文件路径与脚本的目录保持一致
    file_path = os.path.join(current_dir, "fissures.json")
    # 打开 fissures.json 文件并读取其内容
    # 使用 with 语句来自动管理文件的打开与关闭操作
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)  # 将 JSON 数据加载并解析为 Python 对象，通常是列表或字典

    # 从加载的数据中找出 expiry（到期时间）最早的记录
    # 这里使用 min() 函数，通过 lambda 表达式提取每条记录中 expiry 值的日期时间进行比较
    min_time = min(
        data,
        key=lambda record: datetime.fromisoformat(record['expiry']['value'].replace("Z", "+00:00"))
    )
    min_time = str(min_time)
    # 这里可以继续执行其他逻辑，比如异步发送结果到聊天机器人后台
    return min_time
