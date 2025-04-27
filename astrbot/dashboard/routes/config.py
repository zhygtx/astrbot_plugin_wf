import typing
import traceback
from .route import Route, Response, RouteContext
from quart import request
from astrbot.core.config.default import CONFIG_METADATA_2, DEFAULT_VALUE_MAP
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.core_lifecycle import AstrBotCoreLifecycle
from astrbot.core.platform.register import platform_registry
from astrbot.core.provider.register import provider_registry
from astrbot.core.star.star import star_registry
from astrbot.core import logger


def try_cast(value: str, type_: str):
    if type_ == "int":
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    elif (
        type_ == "float"
        and isinstance(value, str)
        and value.replace(".", "", 1).isdigit()
    ):
        return float(value)
    elif type_ == "float" and isinstance(value, int):
        return float(value)
    elif type_ == "float":
        try:
            return float(value)
        except (ValueError, TypeError):
            return None


def validate_config(
    data, schema: dict, is_core: bool
) -> typing.Tuple[typing.List[str], typing.Dict]:
    errors = []

    def validate(data: dict, metadata: dict = schema, path=""):
        for key, value in data.items():
            if key not in metadata:
                # 无 schema 的配置项，执行类型猜测
                if isinstance(value, str):
                    try:
                        data[key] = int(value)
                        continue
                    except ValueError:
                        pass

                    try:
                        data[key] = float(value)
                        continue
                    except ValueError:
                        pass

                    if value.lower() == "true":
                        data[key] = True
                    elif value.lower() == "false":
                        data[key] = False
                continue
            meta = metadata[key]
            if "type" not in meta:
                logger.debug(f"配置项 {path}{key} 没有类型定义, 跳过校验")
                continue
            # null 转换
            if value is None:
                data[key] = DEFAULT_VALUE_MAP[meta["type"]]
                continue
            if meta["type"] == "list" and not isinstance(value, list):
                errors.append(
                    f"错误的类型 {path}{key}: 期望是 list, 得到了 {type(value).__name__}"
                )
            elif (
                meta["type"] == "list"
                and isinstance(value, list)
                and value
                and "items" in meta
                and isinstance(value[0], dict)
            ):
                # 当前仅针对 list[dict] 的情况进行类型校验，以适配 AstrBot 中 platform、provider 的配置
                for item in value:
                    validate(item, meta["items"], path=f"{path}{key}.")
            elif meta["type"] == "object" and isinstance(value, dict):
                validate(value, meta["items"], path=f"{path}{key}.")

            if meta["type"] == "int" and not isinstance(value, int):
                casted = try_cast(value, "int")
                if casted is None:
                    errors.append(
                        f"错误的类型 {path}{key}: 期望是 int, 得到了 {type(value).__name__}"
                    )
                data[key] = casted
            elif meta["type"] == "float" and not isinstance(value, float):
                casted = try_cast(value, "float")
                if casted is None:
                    errors.append(
                        f"错误的类型 {path}{key}: 期望是 float, 得到了 {type(value).__name__}"
                    )
                data[key] = casted
            elif meta["type"] == "bool" and not isinstance(value, bool):
                errors.append(
                    f"错误的类型 {path}{key}: 期望是 bool, 得到了 {type(value).__name__}"
                )
            elif meta["type"] in ["string", "text"] and not isinstance(value, str):
                errors.append(
                    f"错误的类型 {path}{key}: 期望是 string, 得到了 {type(value).__name__}"
                )
            elif meta["type"] == "list" and not isinstance(value, list):
                errors.append(
                    f"错误的类型 {path}{key}: 期望是 list, 得到了 {type(value).__name__}"
                )
            elif meta["type"] == "object" and not isinstance(value, dict):
                errors.append(
                    f"错误的类型 {path}{key}: 期望是 dict, 得到了 {type(value).__name__}"
                )

    if is_core:
        for key, group in schema.items():
            group_meta = group.get("metadata")
            if not group_meta:
                continue
            # logger.info(f"验证配置: 组 {key} ...")
            validate(data, group_meta, path=f"{key}.")
    else:
        validate(data, schema)

    return errors, data


def save_config(post_config: dict, config: AstrBotConfig, is_core: bool = False):
    """验证并保存配置"""
    errors = None
    try:
        if is_core:
            errors, post_config = validate_config(
                post_config, CONFIG_METADATA_2, is_core
            )
        else:
            errors, post_config = validate_config(post_config, config.schema, is_core)
    except BaseException as e:
        logger.error(traceback.format_exc())
        logger.warning(f"验证配置时出现异常: {e}")
        raise ValueError(f"验证配置时出现异常: {e}")
    if errors:
        raise ValueError(f"格式校验未通过: {errors}")
    config.save_config(post_config)


class ConfigRoute(Route):
    def __init__(
        self, context: RouteContext, core_lifecycle: AstrBotCoreLifecycle
    ) -> None:
        super().__init__(context)
        self.core_lifecycle = core_lifecycle
        self.routes = {
            "/config/get": ("GET", self.get_configs),
            "/config/astrbot/update": ("POST", self.post_astrbot_configs),
            "/config/plugin/update": ("POST", self.post_plugin_configs),
            "/config/platform/new": ("POST", self.post_new_platform),
            "/config/platform/update": ("POST", self.post_update_platform),
            "/config/platform/delete": ("POST", self.post_delete_platform),
            "/config/provider/new": ("POST", self.post_new_provider),
            "/config/provider/update": ("POST", self.post_update_provider),
            "/config/provider/delete": ("POST", self.post_delete_provider),
            "/config/llmtools": ("GET", self.get_llm_tools),
        }
        self.register_routes()

    async def get_configs(self):
        # plugin_name 为空时返回 AstrBot 配置
        # 否则返回指定 plugin_name 的插件配置
        plugin_name = request.args.get("plugin_name", None)
        if not plugin_name:
            return Response().ok(await self._get_astrbot_config()).__dict__
        return Response().ok(await self._get_plugin_config(plugin_name)).__dict__

    async def post_astrbot_configs(self):
        post_configs = await request.json
        try:
            await self._save_astrbot_configs(post_configs)
            return Response().ok(None, "保存成功~ 机器人正在重载配置。").__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def post_plugin_configs(self):
        post_configs = await request.json
        plugin_name = request.args.get("plugin_name", "unknown")
        try:
            await self._save_plugin_configs(post_configs, plugin_name)
            await self.core_lifecycle.plugin_manager.reload(plugin_name)
            return (
                Response()
                .ok(None, f"保存插件 {plugin_name} 成功~ 机器人正在热重载插件。")
                .__dict__
            )
        except Exception as e:
            return Response().error(str(e)).__dict__

    async def post_new_platform(self):
        new_platform_config = await request.json
        self.config["platform"].append(new_platform_config)
        try:
            save_config(self.config, self.config, is_core=True)
            await self.core_lifecycle.platform_manager.load_platform(
                new_platform_config
            )
        except Exception as e:
            return Response().error(str(e)).__dict__
        return Response().ok(None, "新增平台配置成功~").__dict__

    async def post_new_provider(self):
        new_provider_config = await request.json
        self.config["provider"].append(new_provider_config)
        try:
            save_config(self.config, self.config, is_core=True)
            await self.core_lifecycle.provider_manager.load_provider(
                new_provider_config
            )
        except Exception as e:
            return Response().error(str(e)).__dict__
        return Response().ok(None, "新增服务提供商配置成功~").__dict__

    async def post_update_platform(self):
        update_platform_config = await request.json
        platform_id = update_platform_config.get("id", None)
        new_config = update_platform_config.get("config", None)
        if not platform_id or not new_config:
            return Response().error("参数错误").__dict__

        for i, platform in enumerate(self.config["platform"]):
            if platform["id"] == platform_id:
                self.config["platform"][i] = new_config
                break
        else:
            return Response().error("未找到对应平台").__dict__

        try:
            save_config(self.config, self.config, is_core=True)
            await self.core_lifecycle.platform_manager.reload(new_config)
        except Exception as e:
            return Response().error(str(e)).__dict__
        return Response().ok(None, "更新平台配置成功~").__dict__

    async def post_update_provider(self):
        update_provider_config = await request.json
        provider_id = update_provider_config.get("id", None)
        new_config = update_provider_config.get("config", None)
        if not provider_id or not new_config:
            return Response().error("参数错误").__dict__

        for i, provider in enumerate(self.config["provider"]):
            if provider["id"] == provider_id:
                self.config["provider"][i] = new_config
                break
        else:
            return Response().error("未找到对应服务提供商").__dict__

        try:
            save_config(self.config, self.config, is_core=True)
            await self.core_lifecycle.provider_manager.reload(new_config)
        except Exception as e:
            return Response().error(str(e)).__dict__
        return Response().ok(None, "更新成功，已经实时生效~").__dict__

    async def post_delete_platform(self):
        platform_id = await request.json
        platform_id = platform_id.get("id")
        for i, platform in enumerate(self.config["platform"]):
            if platform["id"] == platform_id:
                del self.config["platform"][i]
                break
        else:
            return Response().error("未找到对应平台").__dict__
        try:
            save_config(self.config, self.config, is_core=True)
            await self.core_lifecycle.platform_manager.terminate_platform(platform_id)
        except Exception as e:
            return Response().error(str(e)).__dict__
        return Response().ok(None, "删除平台配置成功~").__dict__

    async def post_delete_provider(self):
        provider_id = await request.json
        provider_id = provider_id.get("id")
        for i, provider in enumerate(self.config["provider"]):
            if provider["id"] == provider_id:
                del self.config["provider"][i]
                break
        else:
            return Response().error("未找到对应服务提供商").__dict__
        try:
            save_config(self.config, self.config, is_core=True)
            await self.core_lifecycle.provider_manager.terminate_provider(provider_id)
        except Exception as e:
            return Response().error(str(e)).__dict__
        return Response().ok(None, "删除成功，已经实时生效~").__dict__

    async def get_llm_tools(self):
        """获取函数调用工具。包含了本地加载的以及 MCP 服务的工具"""
        tool_mgr = self.core_lifecycle.provider_manager.llm_tools
        tools = tool_mgr.get_func_desc_openai_style()
        return Response().ok(tools).__dict__

    async def _get_astrbot_config(self):
        config = self.config

        # 平台适配器的默认配置模板注入
        platform_default_tmpl = CONFIG_METADATA_2["platform_group"]["metadata"][
            "platform"
        ]["config_template"]
        for platform in platform_registry:
            if platform.default_config_tmpl:
                platform_default_tmpl[platform.name] = platform.default_config_tmpl

        # 服务提供商的默认配置模板注入
        provider_default_tmpl = CONFIG_METADATA_2["provider_group"]["metadata"][
            "provider"
        ]["config_template"]
        for provider in provider_registry:
            if provider.default_config_tmpl:
                provider_default_tmpl[provider.type] = provider.default_config_tmpl

        return {"metadata": CONFIG_METADATA_2, "config": config}

    async def _get_plugin_config(self, plugin_name: str):
        ret = {"metadata": None, "config": None}

        for plugin_md in star_registry:
            if plugin_md.name == plugin_name:
                if not plugin_md.config:
                    break
                ret["config"] = (
                    plugin_md.config
                )  # 这是自定义的 Dict 类（AstrBotConfig）
                ret["metadata"] = {
                    plugin_name: {
                        "description": f"{plugin_name} 配置",
                        "type": "object",
                        "items": plugin_md.config.schema,  # 初始化时通过 __setattr__ 存入了 schema
                    }
                }
                break

        return ret

    async def _save_astrbot_configs(self, post_configs: dict):
        try:
            save_config(post_configs, self.config, is_core=True)
            await self.core_lifecycle.restart()
        except Exception as e:
            raise e

    async def _save_plugin_configs(self, post_configs: dict, plugin_name: str):
        md = None
        for plugin_md in star_registry:
            if plugin_md.name == plugin_name:
                md = plugin_md

        if not md:
            raise ValueError(f"插件 {plugin_name} 不存在")
        if not md.config:
            raise ValueError(f"插件 {plugin_name} 没有注册配置")

        try:
            save_config(post_configs, md.config)
        except Exception as e:
            raise e
