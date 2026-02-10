"""公共类型定义

Author: afu
"""

from collections.abc import Callable

# (current, total) -- 通用进度回调
ProgressCallback = Callable[[int, int], None]
