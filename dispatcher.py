# 分发器
import importlib.util
from pathlib import Path


# 动态加载模块方案
def load_module(module_name: str):
    module_path = Path(__file__).parent / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


testing = load_module("testing")
fissures = load_module("fissures")


# 异步函数：根据不同的消息内容分发调用相应的功能模块
async def magic_message(message: str) -> str:
    if message == "测试":
        msg = await testing.test(message)
        return msg
    elif message == "蹲":
        msg = fissures.run_fissures_module()
        return msg
    else:
        return "1"
