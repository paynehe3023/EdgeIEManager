"""Edge IE 模式站点列表管理器。

通过 Microsoft Edge 官方支持的“企业模式站点列表(Enterprise Mode Site List)”
机制来管理需要在 IE 模式下打开的网址，避免每月手工到 edge://settings 里点选。
"""

from .version import __version__

__all__ = ["__version__"]
