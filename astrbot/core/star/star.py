from __future__ import annotations

from types import ModuleType
from typing import List, Dict
from dataclasses import dataclass, field
from astrbot.core.config import AstrBotConfig

star_registry: List[StarMetadata] = []
star_map: Dict[str, StarMetadata] = {}
"""key 是模块路径，__module__"""


@dataclass
class StarMetadata:
    """
    插件的元数据。

    当 activated 为 False 时，star_cls 可能为 None，请不要在插件未激活时调用 star_cls 的方法。
    """

    name: str
    author: str  # 插件作者
    desc: str  # 插件简介
    version: str  # 插件版本
    repo: str = None  # 插件仓库地址

    star_cls_type: type = None
    """插件的类对象的类型"""
    module_path: str = None
    """插件的模块路径"""

    star_cls: object = None
    """插件的类对象"""
    module: ModuleType = None
    """插件的模块对象"""
    root_dir_name: str = None
    """插件的目录名称"""
    reserved: bool = False
    """是否是 AstrBot 的保留插件"""

    activated: bool = True
    """是否被激活"""

    config: AstrBotConfig = None
    """插件配置"""

    star_handler_full_names: List[str] = field(default_factory=list)
    """注册的 Handler 的全名列表"""

    supported_platforms: Dict[str, bool] = field(default_factory=dict)
    """插件支持的平台ID字典，key为平台ID，value为是否支持"""

    def __str__(self) -> str:
        return f"StarMetadata({self.name}, {self.desc}, {self.version}, {self.repo})"

    def update_platform_compatibility(self, plugin_enable_config: dict) -> None:
        """更新插件支持的平台列表

        Args:
            plugin_enable_config: 平台插件启用配置，即platform_settings.plugin_enable配置项
        """
        if not plugin_enable_config:
            return

        # 清空之前的配置
        self.supported_platforms.clear()

        # 遍历所有平台配置
        for platform_id, plugins in plugin_enable_config.items():
            # 检查该插件在当前平台的配置
            if self.name in plugins:
                self.supported_platforms[platform_id] = plugins[self.name]
            else:
                # 如果没有明确配置，默认为启用
                self.supported_platforms[platform_id] = True
