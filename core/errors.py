"""NailFit 统一异常：把「调用方输入问题」和「数据/服务问题」分开，便于 API 映射状态码。

分层：
- FeatureError（core/features.py，ValueError 子类）：特征值非法 → 422
- ContractError（core/validator.py，ValueError 子类）：输出契约失败 → 502
- EmptyStyleLibraryError / DataFormatError：服务端数据缺失或损坏 → 503
- NoCandidateError：过滤后可选款式不足 → 422（输入太苛刻或款式库太少）
- VisionUnusableError：手照质量不达标、视觉特征不完整 → 422（提示重拍或手工录入）

之所以都继承 ValueError，是为了兼容旧调用方（`except ValueError` 仍能兜住），
同时新代码可以按具体类型给出不同的状态码和文案。
"""

from __future__ import annotations


class NailFitError(Exception):
    """NailFit 业务异常基类。"""


class DataFormatError(NailFitError, ValueError):
    """数据文件缺失或格式非法（taxonomy / rules / styles）。"""


class EmptyStyleLibraryError(NailFitError, ValueError):
    """款式库为空：文件存在，但里面没有款式。"""


class NoCandidateError(NailFitError, ValueError):
    """过滤后可用款式不足 3 款，无法生成三档推荐。"""


class VisionUnusableError(NailFitError, ValueError):
    """手照质量不达标（握拳/透视过重/手不完整），自动特征不足以直接推荐。"""
