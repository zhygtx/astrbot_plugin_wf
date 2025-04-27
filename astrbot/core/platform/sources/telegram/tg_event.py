import asyncio
import telegramify_markdown
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.platform import AstrBotMessage, PlatformMetadata, MessageType
from astrbot.api.message_components import (
    Plain,
    Image,
    Reply,
    At,
    File,
    Record,
)
from telegram.ext import ExtBot
from astrbot.core.utils.io import download_file
from astrbot import logger


class TelegramPlatformEvent(AstrMessageEvent):
    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        client: ExtBot,
    ):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client

    @staticmethod
    async def send_with_client(client: ExtBot, message: MessageChain, user_name: str):
        image_path = None

        has_reply = False
        reply_message_id = None
        at_user_id = None
        for i in message.chain:
            if isinstance(i, Reply):
                has_reply = True
                reply_message_id = i.id
            if isinstance(i, At):
                at_user_id = i.name

        at_flag = False
        message_thread_id = None
        if "#" in user_name:
            # it's a supergroup chat with message_thread_id
            user_name, message_thread_id = user_name.split("#")
        for i in message.chain:
            payload = {
                "chat_id": user_name,
            }
            if has_reply:
                payload["reply_to_message_id"] = reply_message_id
            if message_thread_id:
                payload["message_thread_id"] = message_thread_id

            if isinstance(i, Plain):
                if at_user_id and not at_flag:
                    i.text = f"@{at_user_id} " + i.text
                    at_flag = True
                text = i.text
                try:
                    text = telegramify_markdown.markdownify(
                        i.text, max_line_length=None, normalize_whitespace=False
                    )
                except Exception as e:
                    logger.warning(
                        f"MarkdownV2 conversion failed: {e}. Using plain text instead."
                    )
                    return
                await client.send_message(text=text, parse_mode="MarkdownV2", **payload)
            elif isinstance(i, Image):
                image_path = await i.convert_to_file_path()
                await client.send_photo(photo=image_path, **payload)
            elif isinstance(i, File):
                if i.file.startswith("https://"):
                    path = "data/temp/" + i.name
                    await download_file(i.file, path)
                    i.file = path

                await client.send_document(document=i.file, filename=i.name, **payload)
            elif isinstance(i, Record):
                path = await i.convert_to_file_path()
                await client.send_voice(voice=path, **payload)

    async def send(self, message: MessageChain):
        if self.get_message_type() == MessageType.GROUP_MESSAGE:
            await self.send_with_client(self.client, message, self.message_obj.group_id)
        else:
            await self.send_with_client(self.client, message, self.get_sender_id())
        await super().send(message)

    async def send_streaming(self, generator, use_fallback: bool = False):
        message_thread_id = None

        if self.get_message_type() == MessageType.GROUP_MESSAGE:
            user_name = self.message_obj.group_id
        else:
            user_name = self.get_sender_id()

        if "#" in user_name:
            # it's a supergroup chat with message_thread_id
            user_name, message_thread_id = user_name.split("#")
        payload = {
            "chat_id": user_name,
        }
        if message_thread_id:
            payload["reply_to_message_id"] = message_thread_id

        delta = ""
        current_content = ""
        message_id = None
        last_edit_time = 0  # 上次编辑消息的时间
        throttle_interval = 0.6  # 编辑消息的间隔时间 (秒)

        async for chain in generator:
            if isinstance(chain, MessageChain):
                # 处理消息链中的每个组件
                for i in chain.chain:
                    if isinstance(i, Plain):
                        delta += i.text
                    elif isinstance(i, Image):
                        image_path = await i.convert_to_file_path()
                        await self.client.send_photo(photo=image_path, **payload)
                        continue
                    elif isinstance(i, File):
                        if i.file.startswith("https://"):
                            path = "data/temp/" + i.name
                            await download_file(i.file, path)
                            i.file = path

                        await self.client.send_document(
                            document=i.file, filename=i.name, **payload
                        )
                        continue
                    elif isinstance(i, Record):
                        path = await i.convert_to_file_path()
                        await self.client.send_voice(voice=path, **payload)
                        continue
                    else:
                        logger.warning(f"不支持的消息类型: {type(i)}")
                        continue

                # Plain
                if not message_id:
                    try:
                        msg = await self.client.send_message(text=delta, **payload)
                        current_content = delta
                    except Exception as e:
                        logger.warning(f"发送消息失败(streaming): {e!s}")
                    message_id = msg.message_id
                    last_edit_time = (
                        asyncio.get_event_loop().time()
                    )  # 记录初始消息发送时间
                else:
                    current_time = asyncio.get_event_loop().time()
                    time_since_last_edit = current_time - last_edit_time

                    # 如果距离上次编辑的时间 >= 设定的间隔，等待一段时间
                    if time_since_last_edit >= throttle_interval:
                        # 编辑消息
                        try:
                            await self.client.edit_message_text(
                                text=delta,
                                chat_id=payload["chat_id"],
                                message_id=message_id,
                            )
                            current_content = delta
                        except Exception as e:
                            logger.warning(f"编辑消息失败(streaming): {e!s}")
                        last_edit_time = (
                            asyncio.get_event_loop().time()
                        )  # 更新上次编辑的时间

        try:
            if delta and current_content != delta:
                try:
                    markdown_text = telegramify_markdown.markdownify(
                        delta, max_line_length=None, normalize_whitespace=False
                    )
                    await self.client.edit_message_text(
                        text=markdown_text,
                        chat_id=payload["chat_id"],
                        message_id=message_id,
                        parse_mode="MarkdownV2",
                    )
                except Exception as e:
                    logger.warning(f"Markdown转换失败，使用普通文本: {e!s}")
                    await self.client.edit_message_text(
                        text=delta, chat_id=payload["chat_id"], message_id=message_id
                    )
        except Exception as e:
            logger.warning(f"编辑消息失败(streaming): {e!s}")

        return await super().send_streaming(generator, use_fallback)
