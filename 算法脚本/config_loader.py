"""
config_loader.py — 全局配置加载器

从 config.yaml 读取所有参数，提供统一的配置访问接口。
替代各脚本中的硬编码常量。
"""
import os
from pathlib import Path

# YAML 支持（Python 3.10+ 标准库无 yaml，需 PyYAML）
try:
    import yaml
except ImportError:
    raise ImportError("需要安装 PyYAML: pip install pyyaml")


class Config:
    """全局配置单例。"""

    _instance = None
    _config = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._config is None:
            self._load()

    def _load(self):
        config_path = Path(__file__).resolve().parent / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        # 展开 ${ENV_VAR} 环境变量引用
        self._config = self._expand_env(raw)

        # 设置 GDAL/PROJ 环境变量（在导入 geopandas 前调用）
        env = self._config.get("env", {})
        gdal_data = env.get("gdal_data", "")
        proj_lib = env.get("proj_lib", "")
        if gdal_data and os.path.exists(gdal_data):
            os.environ.setdefault("GDAL_DATA", gdal_data)
        if proj_lib and os.path.exists(proj_lib):
            os.environ.setdefault("PROJ_LIB", proj_lib)

    def _expand_env(self, obj):
        """递归展开 ${ENV_VAR} 引用。"""
        if isinstance(obj, str):
            if obj.startswith("${") and obj.endswith("}"):
                var_name = obj[2:-1]
                return os.environ.get(var_name, "")
            return obj
        elif isinstance(obj, dict):
            return {k: self._expand_env(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._expand_env(v) for v in obj]
        return obj

    def get(self, *keys, default=None):
        """点号路径访问配置，如 config.get('intensity', 'yu2013', 'c2')。"""
        val = self._config
        for key in keys:
            if isinstance(val, dict) and key in val:
                val = val[key]
            else:
                return default
        return val

    @property
    def raw(self):
        return self._config

    # ── 便捷属性 ──
    @property
    def magnitudes(self):
        return self.get("scenario", "magnitudes", default=[5.0, 5.5, 6.0, 6.5, 7.0, 7.5])

    @property
    def epicenter(self):
        return tuple(self.get("scenario", "epicenter", default=(117.28, 31.82)))

    @property
    def crs_geo(self):
        return self.get("crs", "geo", default="EPSG:4490")

    @property
    def crs_proj(self):
        return self.get("crs", "proj", default="EPSG:4527")

    @property
    def data_dir(self):
        return Path(__file__).resolve().parent.parent / "数据文件"

    @property
    def seed(self):
        return self.get("random", "seed", default=42)


def setup_gdal():
    """在导入 geopandas/osmnx 前调用，设置 GDAL/PROJ 路径。"""
    Config()  # 触发加载


def get_config():
    """获取全局配置实例。"""
    return Config()
