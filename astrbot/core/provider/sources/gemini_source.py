import asyncio
import base64
import json
import logging
import random
from typing import Dict, List, Optional
from collections.abc import AsyncGenerator

from google import genai
from google.genai import types
from google.genai.errors import APIError

import astrbot.core.message.components as Comp
from astrbot import logger
from astrbot.api.provider import Personality, Provider
from astrbot.core.db import BaseDatabase
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.provider.entities import LLMResponse
from astrbot.core.provider.func_tool_manager import FuncCall
from astrbot.core.utils.io import download_image_by_url

from ..register import register_provider_adapter


class SuppressNonTextPartsWarning(logging.Filter):
    """过滤 Gemini SDK 中的非文本部分警告"""

    def filter(self, record):
        return "there are non-text parts in the response" not in record.getMessage()


logging.getLogger("google_genai.types").addFilter(SuppressNonTextPartsWarning())


@register_provider_adapter(
    "googlegenai_chat_completion", "Google Gemini Chat Completion 提供商适配器"
)
class ProviderGoogleGenAI(Provider):
    CATEGORY_MAPPING = {
        "harassment": types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        "hate_speech": types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        "sexually_explicit": types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        "dangerous_content": types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    }

    THRESHOLD_MAPPING = {
        "BLOCK_NONE": types.HarmBlockThreshold.BLOCK_NONE,
        "BLOCK_ONLY_HIGH": types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        "BLOCK_MEDIUM_AND_ABOVE": types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        "BLOCK_LOW_AND_ABOVE": types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    }

    def __init__(
        self,
        provider_config: dict,
        provider_settings: dict,
        db_helper: BaseDatabase,
        persistant_history=True,
        default_persona: Personality = None,
    ) -> None:
        super().__init__(
            provider_config,
            provider_settings,
            persistant_history,
            db_helper,
            default_persona,
        )
        self.api_keys: List = provider_config.get("key", [])
        self.chosen_api_key: str = self.api_keys[0] if len(self.api_keys) > 0 else None
        self.timeout: int = int(provider_config.get("timeout", 180))

        self.api_base: Optional[str] = provider_config.get("api_base", None)
        if self.api_base and self.api_base.endswith("/"):
            self.api_base = self.api_base[:-1]

        self._init_client()
        self.set_model(provider_config["model_config"]["model"])
        self._init_safety_settings()

    def _init_client(self) -> None:
        """初始化Gemini客户端"""
        self.client = genai.Client(
            api_key=self.chosen_api_key,
            http_options=types.HttpOptions(
                base_url=self.api_base,
                timeout=self.timeout * 1000,  # 毫秒
            ),
        ).aio

    def _init_safety_settings(self) -> None:
        """初始化安全设置"""
        user_safety_config = self.provider_config.get("gm_safety_settings", {})
        self.safety_settings = [
            types.SafetySetting(
                category=harm_category, threshold=self.THRESHOLD_MAPPING[threshold_str]
            )
            for config_key, harm_category in self.CATEGORY_MAPPING.items()
            if (threshold_str := user_safety_config.get(config_key))
            and threshold_str in self.THRESHOLD_MAPPING
        ]

    async def _handle_api_error(self, e: APIError, keys: List[str]) -> bool:
        """处理API错误，返回是否需要重试"""
        if e.code == 429 or "API key not valid" in e.message:
            keys.remove(self.chosen_api_key)
            if len(keys) > 0:
                self.set_key(random.choice(keys))
                logger.info(
                    f"检测到 Key 异常({e.message})，正在尝试更换 API Key 重试... 当前 Key: {self.chosen_api_key[:12]}..."
                )
                await asyncio.sleep(1)
                return True
            else:
                logger.error(
                    f"检测到 Key 异常({e.message})，且已没有可用的 Key。 当前 Key: {self.chosen_api_key[:12]}..."
                )
                raise Exception("达到了 Gemini 速率限制, 请稍后再试...")
        else:
            logger.error(
                f"发生了错误(gemini_source)。Provider 配置如下: {self.provider_config}"
            )
            raise e

    async def _prepare_query_config(
        self,
        payloads: dict,
        tools: Optional[FuncCall] = None,
        system_instruction: Optional[str] = None,
        modalities: Optional[List[str]] = None,
        temperature: float = 0.7,
    ) -> types.GenerateContentConfig:
        """准备查询配置"""
        if not modalities:
            modalities = ["Text"]

        # 流式输出不支持图片模态
        if (
            self.provider_settings.get("streaming_response", False)
            and "Image" in modalities
        ):
            logger.warning("流式输出不支持图片模态，已自动降级为文本模态")
            modalities = ["Text"]

        tool_list = None
        native_coderunner = self.provider_config.get("gm_native_coderunner", False)
        native_search = self.provider_config.get("gm_native_search", False)

        if native_coderunner:
            tool_list = [types.Tool(code_execution=types.ToolCodeExecution())]
            if native_search:
                logger.warning("已启用代码执行工具，搜索工具将被忽略")
            if tools:
                logger.warning("已启用代码执行工具，函数工具将被忽略")
        elif native_search:
            tool_list = [types.Tool(google_search=types.GoogleSearch())]
            if tools:
                logger.warning("已启用搜索工具，函数工具将被忽略")
        elif tools and (func_desc := tools.get_func_desc_google_genai_style()):
            tool_list = [
                types.Tool(function_declarations=func_desc["function_declarations"])
            ]
        return types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=payloads.get("max_tokens") or payloads.get("maxOutputTokens"),
            top_p=payloads.get("top_p") or payloads.get("topP"),
            top_k=payloads.get("top_k") or payloads.get("topK"),
            frequency_penalty=payloads.get("frequency_penalty") or payloads.get("frequencyPenalty"),
            presence_penalty=payloads.get("presence_penalty") or payloads.get("presencePenalty"),
            stop_sequences=payloads.get("stop") or payloads.get("stopSequences"),
            response_logprobs=payloads.get("response_logprobs") or payloads.get("responseLogprobs"),
            logprobs=payloads.get("logprobs"),
            seed=payloads.get("seed"),
            response_modalities=modalities,
            tools=tool_list,
            safety_settings=self.safety_settings if self.safety_settings else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

    def _prepare_conversation(self, payloads: Dict) -> List[types.Content]:
        """准备 Gemini SDK 的 Content 列表"""

        def create_text_part(text: str) -> types.UserContent:
            content_a = text if text else " "
            if not text:
                logger.warning("文本内容为空，已添加空格占位")
            return types.UserContent(parts=[types.Part.from_text(text=content_a)])

        def process_image_url(image_url_dict: dict) -> types.Part:
            url = image_url_dict["url"]
            mime_type = url.split(":")[1].split(";")[0]
            image_bytes = base64.b64decode(url.split(",", 1)[1])
            return types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

        gemini_contents: List[types.Content] = []
        native_tool_enabled = any(
            [
                self.provider_config.get("gm_native_coderunner", False),
                self.provider_config.get("gm_native_search", False),
            ]
        )
        for message in payloads["messages"]:
            role, content = message["role"], message.get("content")

            if role == "user":
                if isinstance(content, str):
                    gemini_contents.append(create_text_part(content))
                elif isinstance(content, list):
                    parts = [
                        types.Part.from_text(text=item["text"] or " ")
                        if item["type"] == "text"
                        else process_image_url(item["image_url"])
                        for item in content
                    ]
                    gemini_contents.append(types.UserContent(parts=parts))

            elif role == "assistant":
                if content:
                    gemini_contents.append(
                        types.ModelContent(parts=[types.Part.from_text(text=content)])
                    )
                elif "tool_calls" in message and not native_tool_enabled:
                    gemini_contents.extend(
                        [
                            types.ModelContent(
                                parts=[
                                    types.Part.from_function_call(
                                        name=tool["function"]["name"],
                                        args=json.loads(tool["function"]["arguments"]),
                                    )
                                ]
                            )
                            for tool in message["tool_calls"]
                        ]
                    )
                else:
                    logger.warning("assistant 角色的消息内容为空，已添加空格占位")
                    if native_tool_enabled:
                        logger.warning(
                            "检测到启用Gemini原生工具，且上下文中存在函数调用，建议使用 /reset 重置上下文"
                        )
                    gemini_contents.append(
                        types.ModelContent(parts=[types.Part.from_text(text=" ")])
                    )

            elif role == "tool" and not native_tool_enabled:
                gemini_contents.append(
                    types.UserContent(
                        parts=[
                            types.Part.from_function_response(
                                name=message["tool_call_id"],
                                response={
                                    "name": message["tool_call_id"],
                                    "content": message["content"],
                                },
                            )
                        ]
                    )
                )

        return gemini_contents

    @staticmethod
    def _process_content_parts(
        result: types.GenerateContentResponse, llm_response: LLMResponse
    ) -> MessageChain:
        """处理内容部分并构建消息链"""
        finish_reason = result.candidates[0].finish_reason
        result_parts: Optional[types.Part] = result.candidates[0].content.parts

        if finish_reason == types.FinishReason.SAFETY:
            raise Exception("模型生成内容未通过用户定义的内容安全检查")

        if finish_reason in {
            types.FinishReason.PROHIBITED_CONTENT,
            types.FinishReason.SPII,
            types.FinishReason.BLOCKLIST,
        }:
            raise Exception("模型生成内容违反Gemini平台政策")

        # 防止旧版本SDK不存在IMAGE_SAFETY
        if hasattr(types.FinishReason, "IMAGE_SAFETY"):
            if finish_reason == types.FinishReason.IMAGE_SAFETY:
                raise Exception("模型生成内容违反Gemini平台政策")

        if not result_parts:
            logger.debug(result.candidates)
            raise Exception("API 返回的内容为空。")

        chain = []
        part: types.Part

        # 暂时这样Fallback
        if all(
            part.inline_data and part.inline_data.mime_type.startswith("image/")
            for part in result_parts
        ):
            chain.append(Comp.Plain("这是图片"))
        for part in result_parts:
            if part.text:
                chain.append(Comp.Plain(part.text))
            elif part.function_call:
                llm_response.role = "tool"
                llm_response.tools_call_name.append(part.function_call.name)
                llm_response.tools_call_args.append(part.function_call.args)
                # gemini 返回的 function_call.id 可能为 None
                llm_response.tools_call_ids.append(
                    part.function_call.id or part.function_call.name
                )
            elif part.inline_data and part.inline_data.mime_type.startswith("image/"):
                chain.append(Comp.Image.fromBytes(part.inline_data.data))
        return MessageChain(chain=chain)

    async def _query(
        self, payloads: dict, tools: FuncCall
    ) -> LLMResponse:
        """非流式请求 Gemini API"""
        system_instruction = next(
            (msg["content"] for msg in payloads["messages"] if msg["role"] == "system"),
            None,
        )

        modalities = ["Text"]
        if self.provider_config.get("gm_resp_image_modal", False):
            modalities.append("Image")

        conversation = self._prepare_conversation(payloads)
        temperature=payloads.get("temperature", 0.7)

        result: Optional[types.GenerateContentResponse] = None
        while True:
            try:
                config = await self._prepare_query_config(
                    payloads, tools, system_instruction, modalities, temperature
                )
                result = await self.client.models.generate_content(
                    model=self.get_model(),
                    contents=conversation,
                    config=config,
                )

                if result.candidates[0].finish_reason == types.FinishReason.RECITATION:
                    if temperature > 2:
                        raise Exception("温度参数已超过最大值2，仍然发生recitation")
                    temperature += 0.2
                    logger.warning(
                        f"发生了recitation，正在提高温度至{temperature:.1f}重试..."
                    )
                    continue

                break

            except APIError as e:
                if "Developer instruction is not enabled" in e.message:
                    logger.warning(
                        f"{self.get_model()} 不支持 system prompt，已自动去除(影响人格设置)"
                    )
                    system_instruction = None
                elif "Function calling is not enabled" in e.message:
                    logger.warning(f"{self.get_model()} 不支持函数调用，已自动去除")
                    tools = None
                elif (
                    "Multi-modal output is not supported" in e.message
                    or "Model does not support the requested response modalities"
                    in e.message
                    or "only supports text output" in e.message
                ):
                    logger.warning(
                        f"{self.get_model()} 不支持多模态输出，降级为文本模态"
                    )
                    modalities = ["Text"]
                else:
                    raise
                continue

        llm_response = LLMResponse("assistant")
        llm_response.result_chain = self._process_content_parts(result, llm_response)
        return llm_response

    async def _query_stream(
        self, payloads: dict, tools: FuncCall
    ) -> AsyncGenerator[LLMResponse, None]:
        """流式请求 Gemini API"""
        system_instruction = next(
            (msg["content"] for msg in payloads["messages"] if msg["role"] == "system"),
            None,
        )

        conversation = self._prepare_conversation(payloads)

        result = None
        while True:
            try:
                config = await self._prepare_query_config(
                    payloads, tools, system_instruction
                )
                result = await self.client.models.generate_content_stream(
                    model=self.get_model(),
                    contents=conversation,
                    config=config,
                )
                break
            except APIError as e:
                if "Developer instruction is not enabled" in e.message:
                    logger.warning(
                        f"{self.get_model()} 不支持 system prompt，已自动去除(影响人格设置)"
                    )
                    system_instruction = None
                elif "Function calling is not enabled" in e.message:
                    logger.warning(f"{self.get_model()} 不支持函数调用，已自动去除")
                    tools = None
                else:
                    raise
                continue

        async for chunk in result:
            llm_response = LLMResponse("assistant", is_chunk=True)

            if chunk.candidates[0].content.parts and any(
                part.function_call for part in chunk.candidates[0].content.parts
            ):
                llm_response = LLMResponse("assistant", is_chunk=False)
                llm_response.result_chain = self._process_content_parts(
                    chunk, llm_response
                )
                yield llm_response
                break

            if chunk.text:
                llm_response.result_chain = MessageChain(chain=[Comp.Plain(chunk.text)])
                yield llm_response

            if chunk.candidates[0].finish_reason:
                llm_response = LLMResponse("assistant", is_chunk=False)
                if not chunk.candidates[0].content.parts:
                    llm_response.result_chain = MessageChain(chain=[Comp.Plain(" ")])
                else:
                    llm_response.result_chain = self._process_content_parts(
                        chunk, llm_response
                    )
                yield llm_response
                break

    async def text_chat(
        self,
        prompt: str,
        session_id: str = None,
        image_urls: List[str] = None,
        func_tool: FuncCall = None,
        contexts=[],
        system_prompt=None,
        tool_calls_result=None,
        **kwargs,
    ) -> LLMResponse:
        new_record = await self.assemble_context(prompt, image_urls)
        context_query = [*contexts, new_record]
        if system_prompt:
            context_query.insert(0, {"role": "system", "content": system_prompt})

        for part in context_query:
            if "_no_save" in part:
                del part["_no_save"]

        # tool calls result
        if tool_calls_result:
            context_query.extend(tool_calls_result.to_openai_messages())

        model_config = self.provider_config.get("model_config", {})
        model_config["model"] = self.get_model()

        payloads = {"messages": context_query, **model_config}

        retry = 10
        keys = self.api_keys.copy()

        for _ in range(retry):
            try:
                return await self._query(payloads, func_tool)
            except APIError as e:
                if await self._handle_api_error(e, keys):
                    continue
                break

    async def text_chat_stream(
        self,
        prompt: str,
        session_id: str = None,
        image_urls: List[str] = [],
        func_tool: FuncCall = None,
        contexts=[],
        system_prompt=None,
        tool_calls_result=None,
        **kwargs,
    ) -> AsyncGenerator[LLMResponse, None]:
        new_record = await self.assemble_context(prompt, image_urls)
        context_query = [*contexts, new_record]
        if system_prompt:
            context_query.insert(0, {"role": "system", "content": system_prompt})

        for part in context_query:
            if "_no_save" in part:
                del part["_no_save"]

        # tool calls result
        if tool_calls_result:
            context_query.extend(tool_calls_result.to_openai_messages())

        model_config = self.provider_config.get("model_config", {})
        model_config["model"] = self.get_model()

        payloads = {"messages": context_query, **model_config}

        retry = 10
        keys = self.api_keys.copy()

        for _ in range(retry):
            try:
                async for response in self._query_stream(payloads, func_tool):
                    yield response
                break
            except APIError as e:
                if await self._handle_api_error(e, keys):
                    continue
                break

    async def get_models(self):
        try:
            models = await self.client.models.list()
            return [
                m.name.replace("models/", "")
                for m in models
                if "generateContent" in m.supported_actions
            ]
        except APIError as e:
            raise Exception(f"获取模型列表失败: {e.message}")

    def get_current_key(self) -> str:
        return self.chosen_api_key

    def get_keys(self) -> List[str]:
        return self.api_keys

    def set_key(self, key):
        self.chosen_api_key = key
        self._init_client()

    async def assemble_context(self, text: str, image_urls: List[str] = None):
        """
        组装上下文。
        """
        if image_urls:
            user_content = {
                "role": "user",
                "content": [{"type": "text", "text": text if text else "[图片]"}],
            }
            for image_url in image_urls:
                if image_url.startswith("http"):
                    image_path = await download_image_by_url(image_url)
                    image_data = await self.encode_image_bs64(image_path)
                elif image_url.startswith("file:///"):
                    image_path = image_url.replace("file:///", "")
                    image_data = await self.encode_image_bs64(image_path)
                else:
                    image_data = await self.encode_image_bs64(image_url)
                if not image_data:
                    logger.warning(f"图片 {image_url} 得到的结果为空，将忽略。")
                    continue
                user_content["content"].append(
                    {"type": "image_url", "image_url": {"url": image_data}}
                )
            return user_content
        else:
            return {"role": "user", "content": text}

    async def encode_image_bs64(self, image_url: str) -> str:
        """
        将图片转换为 base64
        """
        if image_url.startswith("base64://"):
            return image_url.replace("base64://", "data:image/jpeg;base64,")
        with open(image_url, "rb") as f:
            image_bs64 = base64.b64encode(f.read()).decode("utf-8")
            return "data:image/jpeg;base64," + image_bs64
        return ""

    async def terminate(self):
        logger.info("Google GenAI 适配器已终止。")
