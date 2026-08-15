"""Chinese literature support helpers."""

from litkit.chinese.acquisition import AcquisitionRequest, append_acquisition_request
from litkit.chinese.normalization import normalize_chinese_key
from litkit.chinese.resources import SZU_CHINESE_RESOURCES, ChineseResource, build_search_targets

__all__ = [
    "AcquisitionRequest",
    "ChineseResource",
    "SZU_CHINESE_RESOURCES",
    "append_acquisition_request",
    "build_search_targets",
    "normalize_chinese_key",
]
