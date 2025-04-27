from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
import importlib.util
from pathlib import Path


# 动态加载模块方案
def load_module(module_name: str):
    module_path = Path(__file__).parent / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dispatcher = load_module("dispatcher")
output = load_module("output")


# 整个插件初始化
@register("warframe组队插件", "zhygtx", "用于群友在群聊中的快速组队", "0.0")
class MyPlugin(Star):
    def __init__(self, context: Context): super().__init__(context)

    async def initialize(self): """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_private_message(self, event: AstrMessageEvent):
        st = event.message_str  # 提取聊天文字
        # 添加类型安全处理
        result = await dispatcher.magic_message(st)  # 转由分发器进行处理
        # 通过输出模块处理结果（需传递事件上下文）
        async for reply in output.output_plugin(event, result):
            yield reply  # 逐条生成回复

    async def terminate(self): """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
