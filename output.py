# 判断所需要输出的类型并返回
from astrbot.api.event import AstrMessageEvent


async def output_plugin(event: AstrMessageEvent, result: str):
    """消息输出处理核心函数
    Args:
        event: 原始消息事件对象（用于生成回复）
        result: 需要输出的处理结果
    Yields:
        消息事件回复对象
    """
    # 类型安全处理
    if not isinstance(result, str):
        result = str(result)

    # 生成纯文本回复（可根据需要扩展其他消息类型）
    yield event.plain_result(result)  # 使用事件对象的回复方法

    # 示例：扩展图片回复（需要时取消注释）
    # if result.startswith("img:"):
    #     yield event.image_result(result[4:])
