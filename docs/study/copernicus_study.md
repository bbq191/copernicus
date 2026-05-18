# Copernicus 项目边做边学笔记

作者：afu

> 不背语法、不刷算法题——直接解剖一个生产级 AI 项目的真实代码，13 课覆盖 Python 全部核心语法，外加 10 个让老手也会拍腿叫绝的工程技巧。

---

## 学习路径概览

```
基础篇
  第一课   变量与数据类型          → config.py
  第二课   数据结构                → task_store.py / lifecycle.py
  第三课   函数 — 从基础到高级     → llm.py / evaluator.py
  第四课   控制流与异常处理         → exceptions.py / llm.py

面向对象篇
  第五课   类基础                  → TaskInfo / Settings
  第六课   类进阶                  → TaskInfo / PipelineContext / llm.py
  第七课   接口、协议与枚举         → pipeline/base.py / schemas/task.py

高级特性篇
  第八课   装饰器                  → config.py / task_store.py
  第九课   推导式与生成器           → task_store.py / routers/
  第十课   异步编程                → task_store.py / lifecycle.py

工程实战篇
  第十一课  项目里 10 个最有趣的技巧（必读）
  第十二课  Pipeline 设计模式      → pipeline/
  第十三课  HTTP 与 API 设计       → routers/
```

---

# 基础篇

---

## 第一课：变量与数据类型

参考文件：`backend/src/copernicus/config.py`

### 1.1 变量：给内存贴标签

计算机运行时，数据活在内存里。变量是你给那块内存起的名字——通过名字来读写数据，不必关心内存地址。

```python
# config.py:10
asr_mode: str = "paraformer"
```

这一行做了三件事：

| 部分             | 含义                           |
| ---------------- | ------------------------------ |
| `asr_mode`       | 变量名（标签）                 |
| `: str`          | 类型注解：这个变量只能装字符串 |
| `= "paraformer"` | 初始值                         |

### 1.2 四种基础类型

```python
asr_mode: str   = "paraformer"   # 文字
asr_batch_size: int   = 3000     # 整数（无小数点）
llm_temperature: float = 0.1     # 浮点数（有小数点）
audio_enhance: bool   = True     # 布尔值，只有 True / False 两个值
```

**为什么不全用 str？**

计算机对 `3000`（int）和 `"3000"`（str）的处理方式完全不同：

- `3000 * 2 = 6000`（数学乘法）
- `"3000" * 2 = "30003000"`（字符串重复！）

类型告诉 Python「用哪种规则处理这份数据」。

### 1.3 None：什么都没有

```python
# config.py:92
hotwords_file: Path | None = None
```

`None` 是 Python 里表示「缺席」的特殊值。类比：抽屉存在，但是空的。

`Path | None` 是**联合类型**：这个变量可以是 `Path`（文件路径），也可以是 `None`（没有路径）。`|` 读作「或者」。

### 1.4 类型注解是给人和工具看的

Python 本身不强制类型——你写错类型注解，程序照样运行。但：

- 编辑器（VSCode / PyCharm）会实时标红警告
- Pydantic 会在运行时真正验证并报错
- 你自己三个月后看代码，也能一眼看懂

这叫**静态类型检查**，是工程化的重要习惯。

### 1.5 Path：比字符串更聪明的路径类型

```python
# config.py:130
templates_dir: Path = Path("./templates")
upload_dir: Path = Path("./uploads")
```

为什么不直接用字符串 `"./uploads"`？

```python
# 字符串拼路径（危险！Windows 用 \，Linux 用 /，拼错就崩）
path = "./uploads" + "/" + task_id + "/" + "transcript.json"

# Path 对象拼路径（正确，跨平台）
path = Path("./uploads") / task_id / "transcript.json"
```

`Path` 的 `/` 运算符被重新定义为路径拼接，帮你处理所有平台差异。这是运算符重载（后面的面向对象篇会讲）。

---

## 第二课：数据结构

参考文件：`task_store.py`、`lifecycle.py`、`pipeline/base.py`

Python 有四种内置集合类型，各有用途：

### 2.1 list（列表）：有序、可重复、可修改

```python
# pipeline/base.py
transcript_entries: list[TranscriptEntry] = field(default_factory=list)
```

```python
entries = []            # 空列表
entries.append(item)    # 末尾添加
entries[0]              # 取第一个（索引从 0 开始）
entries[-1]             # 取最后一个（负数索引从末尾数）
entries[1:3]            # 切片：取第 2、3 个（不含第 4 个）
len(entries)            # 长度
for e in entries:       # 遍历
    print(e)
```

**类比**：排好队的人——顺序重要，可以插队、离队，同一个人可以排两次。

### 2.2 dict（字典）：键值对、按名字取数据

```python
# task_store.py:24-32
_PIPELINE_STAGE_STATUS: dict[str, TaskStatus] = {
    "video_preprocess":  "extracting_frames",
    "asr_transcribe":    "processing_asr",
    "text_correction":   "correcting",
}
```

```python
d = {"name": "afu", "age": 40}
d["name"]           # "afu"（取值，不存在会报 KeyError）
d.get("email")      # None（不存在返回默认值，不报错）
d.get("email", "")  # ""（自定义默认值）
d["city"] = "SH"    # 新增或修改
"name" in d         # True（检查 key 是否存在）
d.keys()            # 所有 key
d.values()          # 所有 value
d.items()           # 所有 (key, value) 对
```

**重要特性**：Python 3.7+ 的 dict **保留插入顺序**。`task_store.py` 里的任务淘汰逻辑正是利用这一点——最早插入的任务排在最前面，最先被淘汰（见第十一课技巧 7）。

### 2.3 tuple（元组）：有序、不可修改

```python
# lifecycle.py:14
_KEEP_FILES = frozenset({
    "transcript.json",
    "evaluation.json",
    ...
})
```

tuple 和 list 的区别：

```python
lst = [1, 2, 3]   # list，可以改
tpl = (1, 2, 3)   # tuple，创建后不能改
tpl[0] = 99        # 报错！TypeError
```

**什么时候用 tuple？** 当数据创建后不应该被修改时——比如坐标 `(x, y)`、RGB 颜色 `(255, 0, 0)`、数据库记录。不可变意味着**安全**，可以放心传来传去不会被意外修改。

### 2.4 set（集合）：无序、不重复、快速查找

```python
# routers/task.py:22-26
_VIDEO_EXTENSIONS = {
    e.strip().lower()
    for e in settings.video_extensions.split(",")
    if e.strip()
}
# 结果：{".mp4", ".avi", ".mov", ".mkv", ...}
```

```python
s = {".mp4", ".avi", ".mp4"}  # {".mp4", ".avi"}，自动去重
".mp4" in s                    # True（查找速度极快，O(1)）
s.add(".flv")
s.remove(".avi")
```

**为什么用 set 而不是 list 判断扩展名？**

```python
# list 查找：从头遍历，最坏情况要看完所有元素（O(n)）
".mp4" in [".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"]

# set 查找：哈希表，直接定位，无论多少元素都是 O(1)
".mp4" in {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"}
```

对于「判断某个值在不在这个集合里」的场景，set 比 list 快得多。

### 2.5 frozenset：不可变的 set

```python
# lifecycle.py:14
_KEEP_FILES = frozenset({
    "transcript.json",
    "evaluation.json",
    "compliance.json",
})
```

`frozenset` 是 `set` 的只读版本——所有查找操作都支持，但不能增删元素。

用 `frozenset` 而不是 `set` 的原因：这是模块级常量，定义后永远不该被修改。`frozenset` 从语言层面强制了这个约束。

### 2.6 四种结构对比

| 特性       | list     | dict         | tuple    | set           |
| ---------- | -------- | ------------ | -------- | ------------- |
| 有序       | 是       | 是（插入序） | 是       | 否            |
| 可修改     | 是       | 是           | 否       | 是            |
| 允许重复   | 是       | key 不重复   | 是       | 否            |
| 按什么取值 | 数字索引 | 任意 key     | 数字索引 | 不能取单个    |
| 典型用途   | 有序集合 | 映射/翻译表  | 固定记录 | 去重/快速查找 |

---

## 第三课：函数 — 从基础到高级

参考文件：`evaluator.py`、`llm.py`、`pipeline/orchestrator.py`

### 3.1 函数的本质

函数是「打包好的操作流程」，起个名字，随时调用，避免重复代码。

```python
# 基本结构
def 函数名(参数1, 参数2) -> 返回值类型:
    # 函数体
    return 结果
```

```python
# evaluator.py:27-37
def build_map_prompt(template_prompt: str) -> str:
    return f"""你是一个专业的内容分析助手。
任务：阅读给定的文本片段，为最终的【目标模版】提取所有相关的核心素材。

【最终要生成的模版参考】
{template_prompt}
..."""
```

这里用了 **f-string**（格式化字符串）：`f"..."` 里的 `{变量名}` 会被替换成变量的值。是 Python 里最常用的字符串拼接方式。

### 3.2 参数的四种形式

```python
# 1. 位置参数：按顺序传入
def add(a, b):
    return a + b
add(1, 2)  # a=1, b=2

# 2. 默认值：不传就用默认
def greet(name, greeting="你好"):
    return f"{greeting}, {name}"
greet("afu")           # "你好, afu"
greet("afu", "早上好")  # "早上好, afu"

# 3. 关键字参数：按名字传，顺序无所谓
greet(greeting="晚上好", name="afu")

# 4. keyword-only 参数（* 之后的参数必须用关键字传）
# task_store.py:211
def submit_transcript(self, audio_bytes, filename, hotwords,
                      *, file_hash="", visual_scan=False):
    ...
# 调用时 file_hash 和 visual_scan 必须明确写出来：
store.submit_transcript(data, "file.mp3", None, file_hash="abc", visual_scan=True)
# 这样做防止调用方记错参数顺序，弄混 file_hash 和 visual_scan
```

### 3.3 `*args` 和 `**kwargs`：接收任意数量的参数

```python
def log(*args, **kwargs):
    # args 是一个 tuple，装所有位置参数
    # kwargs 是一个 dict，装所有关键字参数
    print(args)   # (1, 2, 3)
    print(kwargs) # {"name": "afu", "age": 40}

log(1, 2, 3, name="afu", age=40)
```

### 3.4 嵌套函数与闭包

函数里面可以再定义函数。内层函数可以「记住」外层函数的变量：

```python
# task_store.py:470-479
def on_stage_change(stage_name: str) -> None:
    new_status = _PIPELINE_STAGE_STATUS.get(stage_name)
    if new_status:
        task.status = TaskStatus(new_status)  # task 是外层的变量！

def on_progress(current: int, total: int) -> None:
    task.current_chunk = current  # task 是外层的变量！
    task.total_chunks = total
```

`on_progress` 是定义在 `_execute_pipeline` 里的嵌套函数，它「捕获」了外层的 `task` 变量。这叫**闭包（Closure）**。

好处：不需要把 `task` 当参数传进去，函数自动记住它。

### 3.5 lambda：一行匿名函数

```python
# main.py:86-88
model_manager.register_loader(
    "asr",
    loader=lambda: (asr_service.reload(), asr_service)[1],
    unloader=lambda _: asr_service.unload_weights(),
)
```

`lambda` 创建一个没有名字的简单函数：

```python
lambda 参数: 表达式

# 等价于：
def 匿名(参数):
    return 表达式
```

`lambda: (asr_service.reload(), asr_service)[1]` 这行有点绕：

1. 先执行 `asr_service.reload()`（没有返回值，结果是 None）
2. 把 `(None, asr_service)` 当成 tuple
3. 取 `[1]` 也就是 `asr_service`

本质是：在调用 reload() 的同时返回 asr_service 对象。一行搞定两件事。

---

## 第四课：控制流与异常处理

参考文件：`exceptions.py`、`llm.py`

### 4.1 条件判断

```python
if 条件:
    ...
elif 另一个条件:
    ...
else:
    ...
```

Python 的条件判断里，这些值被视为 `False`：

```python
False, None, 0, 0.0, "", [], {}, set()
```

所以可以简写：

```python
# 不用写 if hotwords != None and len(hotwords) > 0:
if hotwords:
    ...

# 不用写 if len(tasks) == 0:
if not tasks:
    ...
```

### 4.2 for 循环

```python
# 遍历列表
for stage in self._stages:
    stage.execute(ctx)

# 同时取索引和值（enumerate）
for i, stage in enumerate(self._stages):
    print(f"Stage {i}: {stage.name}")

# 遍历字典
for key, value in d.items():
    print(f"{key} = {value}")

# range：生成数字序列
for attempt in range(1, max_attempts + 1):  # 1, 2, 3, ..., max_attempts
    ...
```

### 4.3 while 循环

```python
# lifecycle.py:65-72
async def run_periodic(self, interval_seconds: int = 3600) -> None:
    while True:              # 无限循环
        await asyncio.sleep(interval_seconds)
        try:
            await asyncio.to_thread(self.cleanup_expired_media)
        except Exception as e:
            logger.warning("Lifecycle cleanup error: %s", e)
```

`while True` + `await asyncio.sleep()` 是后台定时任务的标准写法：永远跑，每次睡一段时间，醒来干活，再睡。

### 4.4 异常处理：try / except / finally

```python
try:
    有可能失败的代码
except 某种错误类型 as e:
    出错时的处理
except (错误A, 错误B) as e:
    同时捕获多种错误
finally:
    无论成功失败都执行（通常用于清理资源）
```

真实例子（llm.py:94-120）：

```python
for attempt in range(1, max_attempts + 1):
    try:
        async with self._semaphore:
            return await self._do_chat(messages, ...)
    except (httpx.ReadTimeout, httpx.ConnectError, httpx.HTTPStatusError) as e:
        last_error = e
        if attempt >= max_attempts:
            raise                          # 重新抛出，不再重试
        delay = self._retry_delay * (2 ** (attempt - 1))  # 指数退避
        await asyncio.sleep(delay)
```

这段代码实现了**指数退避重试**：

- 第 1 次失败：等 2 秒
- 第 2 次失败：等 4 秒
- 第 3 次失败：等 8 秒
- 之后直接抛出错误

`2 ** (attempt - 1)` 是指数运算：`2^0=1, 2^1=2, 2^2=4`，乘以 `retry_delay=2.0` 得到 `2, 4, 8`。

### 4.5 自定义异常：建立错误体系

```python
# exceptions.py（完整文件）
class CopernicusError(Exception):
    """Base exception for Copernicus service."""

class AudioProcessingError(CopernicusError):
    """Raised when audio preprocessing fails."""

class ASRError(CopernicusError):
    """Raised when ASR inference fails."""

class CorrectionError(CopernicusError):
    """Raised when LLM text correction fails."""
```

这是一棵异常继承树：

```
Exception（Python 内置）
    └── CopernicusError（项目基础异常）
            ├── AudioProcessingError
            ├── ASRError
            └── CorrectionError
```

好处：调用方可以按需捕获：

```python
except CopernicusError:      # 捕获所有项目异常
except ASRError:             # 只捕获 ASR 错误
```

子类异常会被父类的 `except` 捕获，但反过来不行。这就是**异常继承**的用途。

### 4.6 raise：主动抛出错误

```python
if self._evaluator is None:
    raise RuntimeError("EvaluatorService not configured")
```

`raise` 让程序立刻停止当前函数，把错误传给调用方处理。是比 `return None` 更明确的失败信号——调用方不得不处理它，否则程序崩溃。

---

# 面向对象篇

---

## 第五课：类基础

参考文件：`task_store.py`（TaskInfo）、`config.py`（Settings）

### 5.1 类：设计图纸

```python
class TaskInfo:
    def __init__(self, task_id: str, *, eval_only: bool = False) -> None:
        self.task_id = task_id
        self.status = TaskStatus.PENDING
        self.current_chunk = 0
        self.total_chunks = 0
        self.result = None
        self.error = None
        self.eval_only = eval_only
```

- `class TaskInfo:` 定义类（设计图纸）
- `def __init__(self, ...)` 是构造方法：创建实例时自动调用
- `self` 是实例本身的引用，通过 `self.xxx` 给实例附加属性

```python
# 用类创建实例（按图纸建房子）
info = TaskInfo("abc123")
info.task_id    # "abc123"
info.status     # TaskStatus.PENDING
```

### 5.2 继承：复用与扩展

```python
# config.py:6
class Settings(BaseSettings):
    asr_mode: str = "paraformer"
    ...
```

`Settings` 继承自 `BaseSettings`，获得了 BaseSettings 的所有能力：

- 自动读取环境变量
- 自动读取 `.env` 文件
- 属性变更时自动验证类型

同时，Settings 添加了自己的配置项。这就是继承的核心价值：**站在巨人的肩膀上**。

### 5.3 `__dunder__` 方法：Python 的魔法协议

双下划线包裹的方法叫 dunder 方法（double underscore），是 Python 内置的「钩子」：

```python
class Path:
    def __truediv__(self, other):  # 重载 / 运算符
        return Path(str(self) + "/" + str(other))

# 于是可以写：
Path("uploads") / "abc" / "transcript.json"
```

常用 dunder 方法：

| 方法           | 触发时机                   |
| -------------- | -------------------------- |
| `__init__`     | `MyClass()` 创建实例       |
| `__str__`      | `str(obj)` 或 `print(obj)` |
| `__repr__`     | 调试时显示对象             |
| `__len__`      | `len(obj)`                 |
| `__contains__` | `item in obj`              |
| `__truediv__`  | `a / b`                    |
| `__eq__`       | `a == b`                   |
| `__lt__`       | `a < b`                    |

### 5.4 类属性 vs 实例属性

```python
class TaskStore:
    MAX_TASKS = 500          # 类属性：所有实例共享，通过 TaskStore.MAX_TASKS 访问

    def __init__(self):
        self._tasks = {}     # 实例属性：每个实例独立，通过 self._tasks 访问
```

**命名约定**：Python 没有真正的私有属性，但约定：

- `_name`（单下划线）：内部实现，不建议外部直接用
- `__name`（双下划线）：强制私有，Python 会改写名字防止子类意外覆盖
- `name`（无下划线）：公开接口

---

## 第六课：类进阶

参考文件：`task_store.py`（`__slots__`、`@property`）、`pipeline/base.py`（`@dataclass`）、`llm.py`（`frozen=True`）

### 6.1 `@property`：像属性一样调用的函数

```python
# config.py:136-138
@property
def max_upload_size_bytes(self) -> int:
    return self.max_upload_size_mb * 1024 * 1024
```

```python
# 调用方不需要加括号，像访问普通属性一样
settings.max_upload_size_bytes   # 不是 settings.max_upload_size_bytes()
```

**为什么用 @property 而不是普通属性？**

- 普通属性：`self.max_upload_size_bytes = 500 * 1024 * 1024`，改了 `max_upload_size_mb` 后不会自动更新
- @property：每次访问都重新计算，始终和 `max_upload_size_mb` 保持同步

`@property` 把「计算过程」伪装成「数据属性」，调用方无需关心它是存储的还是计算的。

### 6.2 `__slots__`：内存优化

```python
# task_store.py:36-46
class TaskInfo:
    __slots__ = (
        "task_id", "status", "current_chunk",
        "total_chunks", "result", "error",
        "eval_only", "audio_path", "parent_task_id",
    )
```

Python 默认用一个隐藏字典（`__dict__`）存储每个实例的属性，允许随时添加新属性：

```python
info = TaskInfo("abc")
info.new_field = "随意添加"  # 没有 __slots__ 时合法
```

加了 `__slots__` 后：

- 实例只能有声明过的属性，添加新属性报错
- 没有 `__dict__`，每个实例内存占用减少约 40%

系统可能同时存在几百个 `TaskInfo`，`__slots__` 带来的节省相当可观。

### 6.3 `@dataclass`：自动生成构造函数

```python
# pipeline/base.py:21-29
@dataclass
class TranscriptEntry:
    timestamp: str
    timestamp_ms: int
    end_ms: int
    speaker: str
    text: str
    text_corrected: str
```

`@dataclass` 自动生成以下方法：

- `__init__(self, timestamp, timestamp_ms, ...)` — 构造函数
- `__repr__(self)` — 调试显示
- `__eq__(self, other)` — 相等比较

不加 `@dataclass`，你需要手写所有这些。加了之后，只需声明字段，Python 自动处理剩余工作。

### 6.4 `@dataclass(frozen=True)`：不可变数据类

```python
# llm.py:24-26
@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str
```

`frozen=True` 让实例创建后无法修改任何字段。尝试修改会报 `FrozenInstanceError`。

**为什么用 frozen？**

`ChatMessage` 是发给 LLM 的消息，创建后就不该变。用 `frozen=True` 从语言层面保证它不会被意外修改，避免一类 bug。

### 6.5 `field(default_factory=...)`：可变默认值的正确写法

```python
# pipeline/base.py:63-64
@dataclass
class PipelineContext:
    segments: list[Segment] = field(default_factory=list)
    correction_map: dict[int, str] = field(default_factory=dict)
```

**Python 的一个著名陷阱：**

```python
# 错误写法！
@dataclass
class Bad:
    items: list = []   # 所有实例共享同一个列表！

a = Bad()
b = Bad()
a.items.append(1)
print(b.items)   # [1]  ← b 的 items 也变了！！
```

原因：`[]` 在类定义时只创建一次，所有实例共享同一个对象。

`field(default_factory=list)` 的意思是：「每次创建新实例，调用 `list()` 生成一个全新的空列表」。这样每个实例都有自己独立的列表。

---

## 第七课：接口、协议与枚举

参考文件：`pipeline/base.py`（Protocol）、`schemas/task.py`（Enum）

### 7.1 Protocol：定义接口契约

```python
# pipeline/base.py:78-90
@runtime_checkable
class Stage(Protocol):
    name: str

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext: ...

    def should_run(self, ctx: PipelineContext) -> bool: ...
```

`Protocol` 定义了一份「合同」：任何满足这份合同的类，都可以当成 `Stage` 使用。

合同内容只有两条：

1. 有 `execute()` 方法
2. 有 `should_run()` 方法

**Protocol 和继承的区别：**

```python
# 继承方式：必须显式声明
class MyStage(Stage):  # "我继承自 Stage"
    ...

# Protocol 方式：鸭子类型（Duck Typing）
class MyStage:         # 不需要继承 Stage
    name = "my_stage"
    async def execute(self, ctx, on_progress=None): ...
    def should_run(self, ctx): ...
    # 只要实现了这两个方法，就自动满足 Stage Protocol
```

> 「如果它走路像鸭子，叫声像鸭子，那它就是鸭子。」

### 7.2 `@runtime_checkable`：允许运行时检查

```python
@runtime_checkable
class Stage(Protocol):
    ...

# 没有 @runtime_checkable，这行会报错
# 有了它，可以在运行时检查对象是否满足 Protocol
isinstance(my_stage, Stage)  # True 或 False
```

### 7.3 Enum：有限选项集合

```python
# schemas/task.py:10-19
class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING_ASR = "processing_asr"
    COMPLETED = "completed"
    FAILED = "failed"
    ...
```

**StrEnum 的特殊之处**：枚举值同时也是字符串。

```python
TaskStatus.COMPLETED == "completed"  # True
str(TaskStatus.COMPLETED)            # "completed"
```

这非常方便——既有枚举的类型安全，又可以直接当字符串用于 JSON 序列化。

**为什么用 Enum 而不用字符串常量？**

```python
# 字符串常量：拼错不报错
STATUS_COMPLETED = "completed"
if task.status == "compelted":  # 拼错了，Python 不会提示

# Enum：拼错直接 AttributeError
if task.status == TaskStatus.COMPELTED:  # AttributeError！
```

---

# 高级特性篇

---

## 第八课：装饰器 — 给函数穿外套

### 8.1 装饰器的本质

装饰器是一个函数，它接收另一个函数，返回一个增强版的函数。

```python
def my_decorator(func):
    def wrapper(*args, **kwargs):
        print("函数执行前")
        result = func(*args, **kwargs)   # 调用原函数
        print("函数执行后")
        return result
    return wrapper

@my_decorator
def say_hello():
    print("Hello!")

# say_hello() 等价于 my_decorator(say_hello)()
say_hello()
# 输出：
# 函数执行前
# Hello!
# 函数执行后
```

`@my_decorator` 只是语法糖，相当于 `say_hello = my_decorator(say_hello)`。

### 8.2 项目里的装饰器

```python
@property              # 把方法变成属性访问
@staticmethod          # 类的静态方法，不需要 self
@classmethod           # 类方法，第一个参数是 cls（类本身）
@asynccontextmanager   # 把 async 生成器变成上下文管理器
@dataclass             # 自动生成 __init__ 等方法
@runtime_checkable     # 允许 isinstance 检查 Protocol
@router.post(...)      # FastAPI 路由注册
```

### 8.3 `@staticmethod` 和 `@classmethod`

```python
class TaskStore:
    @staticmethod
    def _is_terminal(status: TaskStatus) -> bool:
        # 不需要 self，因为不访问实例数据
        return status in (TaskStatus.COMPLETED, TaskStatus.FAILED)

    @classmethod
    def create_default(cls) -> "TaskStore":
        # cls 是 TaskStore 类本身，可以用来创建实例
        return cls(pipeline=DefaultPipeline())
```

- `@staticmethod`：函数碰巧放在类里，实际上和实例无关
- `@classmethod`：操作类本身，常用于工厂方法（创建实例的另一种方式）

### 8.4 装饰器叠加

```python
@router.post("/tasks/standard_minutes", response_model=TaskSubmitResponse, status_code=202)
async def submit_standard_minutes_task(...):
    ...
```

多个装饰器从下往上依次应用：先应用 `@router.post(...)`，结果再给上一层。

---

## 第九课：推导式与生成器 — Python 最优雅的语法

### 9.1 列表推导式

```python
# 基本形式：[表达式 for 变量 in 可迭代对象 if 条件]
squares = [x ** 2 for x in range(10)]
# [0, 1, 4, 9, 16, 25, 36, 49, 64, 81]

# 带条件
evens = [x for x in range(10) if x % 2 == 0]
# [0, 2, 4, 6, 8]
```

等价于：

```python
result = []
for x in range(10):
    if x % 2 == 0:
        result.append(x)
```

推导式更简洁，且通常更快（CPython 内部优化）。

### 9.2 字典推导式

```python
# {key表达式: value表达式 for 变量 in 可迭代对象}
name_to_status = {
    stage.name: stage.should_run(ctx)
    for stage in self._stages
}
```

### 9.3 集合推导式

```python
# routers/task.py:22-26（实际代码）
_VIDEO_EXTENSIONS = {
    e.strip().lower()
    for e in settings.video_extensions.split(",")
    if e.strip()
}
```

这一行做了：

1. 把 `".mp4,.avi,.mov"` 按逗号分割 → `[".mp4", ".avi", ".mov"]`
2. 每个元素去掉空格、转小写
3. 跳过空字符串（`if e.strip()`）
4. 放进 set（自动去重）

等价于 7 行的 for 循环。

### 9.4 生成器表达式：惰性计算，节省内存

```python
# task_store.py:359
full_text = "\n".join(e.text_corrected for e in transcript.transcript)
```

`(e.text_corrected for e in transcript.transcript)` 是生成器表达式（不是 tuple，没有 `[`）。

**列表推导式 vs 生成器表达式：**

```python
# 列表推导式：立即计算，全部放入内存
texts = [e.text_corrected for e in entries]   # 内存：N 份字符串

# 生成器表达式：惰性计算，一次只有一个
texts = (e.text_corrected for e in entries)    # 内存：几乎为 0
```

`"\n".join()` 只需要逐个取字符串，不需要全部同时存在内存里，所以生成器表达式更合适。

当 transcript 有几千句话时，这个区别非常明显。

### 9.5 yield：函数变生成器

```python
def count_up():
    yield 1
    yield 2
    yield 3

for n in count_up():
    print(n)  # 1, 2, 3（依次输出）
```

`yield` 让函数变成生成器：每次调用 `next()` 时运行到下一个 `yield` 处暂停。调用方每次只拿一个值，函数「冻结」在 yield 处等待下次调用。

**在上下文管理器里的特殊用法：**

```python
# task_store.py:407-420
@asynccontextmanager
async def _task_lifecycle(self, task_id: str, label: str):
    task = self._tasks[task_id]
    try:
        yield task       # ← 在这里「暂停」，把 task 交给 with 块使用
        task.status = TaskStatus.COMPLETED
    except Exception as e:
        task.status = TaskStatus.FAILED
```

`yield` 之前是「进入」逻辑，`yield` 之后是「退出」逻辑，`yield` 本身是「暂停点」。

---

## 第十课：异步编程

参考文件：`task_store.py`、`lifecycle.py`、`llm.py`

### 10.1 为什么需要异步？

音频转录需要 30-120 秒。如果用同步代码：

```python
# 同步：阻塞！
result = run_asr(audio)  # 等 60 秒
return result
```

这 60 秒里，整个服务器什么都不能干。如果有 10 个用户同时上传，只能排队，第 10 个用户要等 10 分钟。

异步解决方案：

```python
# 异步：不阻塞
result = await run_asr_async(audio)  # 挂起，让其他任务先跑
```

`await` 把执行权「还给」事件循环，事件循环去处理其他任务，ASR 完成后回来继续。

### 10.2 `async def` / `await`

```python
async def get_task_status(task_id: str) -> TaskStatusResponse:
    task = store.get(task_id)      # 普通调用
    return TaskStatusResponse(...)  # 普通返回
```

- `async def` 定义异步函数（也叫协程）
- 异步函数必须用 `await` 调用，或者用 `asyncio.create_task()` 丢进后台

```python
# 错误：忘记 await，拿到的是协程对象，不是结果
result = get_task_status("abc")  # <coroutine object>

# 正确
result = await get_task_status("abc")  # TaskStatusResponse
```

### 10.3 `asyncio.create_task()`：后台执行

```python
# task_store.py:222-230
def submit_standard_minutes(self, ...) -> str:
    task_id = uuid.uuid4().hex
    self._register_task(task_id)
    asyncio.create_task(              # 扔进后台，不等待
        self._run_with_timeout(
            task_id,
            self._run_standard_minutes(...),
        )
    )
    return task_id                    # 立刻返回
```

`create_task` 把协程丢进后台运行，当前函数立刻返回。这是「提交任务 → 返回 ID → 轮询状态」模式的关键。

### 10.4 `asyncio.wait_for()`：设置超时

```python
# task_store.py:394-403
async def _run_with_timeout(self, task_id: str, coro) -> None:
    try:
        await asyncio.wait_for(coro, timeout=self._task_timeout)
    except asyncio.TimeoutError:
        task = self._tasks.get(task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.error = f"任务超时（{self._task_timeout}s）"
```

`wait_for` 给协程加一个秒表：超时未完成，自动抛 `asyncio.TimeoutError`。防止 ASR 或 LLM 卡住导致任务永远挂着。

### 10.5 `asyncio.Semaphore`：并发限制

```python
# llm.py:54
self._semaphore = asyncio.Semaphore(settings.llm_max_concurrent)  # 默认 3

# llm.py:96-105
async with self._semaphore:    # 同时最多 3 个任务能进入这里
    return await self._do_chat(...)
```

`Semaphore(3)` 就像一扇只有 3 个「令牌」的门：进入时取走一个令牌，离开时归还。没有令牌时等待。

防止同时向 LLM 发送太多请求导致显存溢出（OOM）。

### 10.6 `asyncio.to_thread()`：在异步代码里运行同步函数

```python
# lifecycle.py:70
await asyncio.to_thread(self.cleanup_expired_media)
```

`cleanup_expired_media` 是普通同步函数（扫描文件、删除文件）。直接在异步代码里调用它会阻塞事件循环。

`asyncio.to_thread()` 把它丢到线程池里运行，主事件循环继续处理其他任务，线程完成后再回来。

---

# 工程实战篇

---

## 第十一课：项目里 10 个最有趣的代码技巧

这是整个教程最有意思的部分——真实工程代码里的精妙设计。

---

### 技巧 1：闭包的「晚绑定陷阱」及工厂函数解法

**文件**：`pipeline/orchestrator.py:44-49`

这是 Python 里最著名的陷阱之一，大多数人都会踩。

```python
# orchestrator.py（真实代码）
for stage in self._stages:
    if on_stage_progress:
        def _make_cb(name: str, idx: int) -> ProgressCallback:
            def _cb(current: int, total_items: int) -> None:
                on_stage_progress(name, idx, total, current, total_items)
            return _cb
        stage_progress = _make_cb(stage.name, executed - 1)
```

**为什么不直接这样写？**

```python
# 看起来合理，但有 bug！
for stage in self._stages:
    if on_stage_progress:
        def stage_progress(current, total_items):
            on_stage_progress(stage.name, ...)  # stage.name 是引用，不是值！
```

Python 的闭包捕获的是**变量的引用**，不是变量当前的值。循环结束后，`stage` 指向最后一个 Stage，所有闭包里的 `stage.name` 都是最后一个 Stage 的名字。

**工厂函数解法**：`_make_cb(name, idx)` 把 `stage.name` 作为参数传入，参数是值的拷贝，和外层变量脱钩。每次调用 `_make_cb` 创建一个新的局部作用域，捕获的是那次调用时的值。

这个技巧在处理循环内回调时几乎总是必要的。

---

### 技巧 2：`or` 作为空值默认值

**文件**：`main.py:9`

```python
os.environ["LOKY_MAX_CPU_COUNT"] = str(os.cpu_count() or 8)
```

`or` 不只是布尔运算符。`A or B` 的返回值：

- 如果 A 是「真值」，返回 A
- 如果 A 是「假值」，返回 B

`os.cpu_count()` 在某些虚拟机环境下可能返回 `None`，`None or 8` 返回 `8`。

一行代码实现「有就用，没有就用默认值」，比 `if x is None: x = 8` 更简洁。

---

### 技巧 3：`max(x, 1)` 防除零

**文件**：`task_store.py:104`

```python
percent = 20.0 + (self.current_chunk / max(self.total_chunks, 1)) * 70.0
```

`total_chunks` 初始为 0，直接除会触发 `ZeroDivisionError`。

`max(total_chunks, 1)` 保证分母至少为 1，零变成 1，结果是 0/1=0%，符合「还没开始」的语义。

这个技巧的精髓：用数学约束代替 if 判断，代码更紧凑，也更难遗漏。

---

### 技巧 4：`time.perf_counter()` 高精度计时

**文件**：`orchestrator.py:51-54`

```python
start = time.perf_counter()
ctx = await stage.execute(ctx, on_progress=stage_progress)
elapsed = (time.perf_counter() - start) * 1000
ctx.processing_times[stage.name] = elapsed
```

`time.perf_counter()` 返回高精度计数器的值（单位：秒，精度纳秒级）。

`time.time()` 是系统时钟，会受 NTP 时间同步、闰秒等影响，不适合测量间隔。`perf_counter()` 是单调递增的硬件计数器，专门用于性能测量。

乘以 1000 转换为毫秒，记录到 `processing_times` 字典里，可以看到每个 Stage 各花了多少时间。

---

### 技巧 5：`str.removeprefix()` Python 3.9 新语法

**文件**：`routers/upload.py:89`

```python
range_spec = content_range.removeprefix("bytes ")
# "bytes 0-1048575/104857600" → "0-1048575/104857600"
```

Python 3.9 新增。旧写法：

```python
if content_range.startswith("bytes "):
    range_spec = content_range[6:]  # 硬编码长度，容易出错
```

`removeprefix` 语义清晰，不需要手数字符长度。

类似的还有 `removesuffix()`：

```python
"transcript.json".removesuffix(".json")  # "transcript"
```

---

### 技巧 6：`Path.unlink(missing_ok=True)` 优雅删除

**文件**：`lifecycle.py:57`

```python
f.unlink(missing_ok=True)
```

删除文件。`missing_ok=True` 表示：如果文件不存在，不报错，静默忽略。

旧写法：

```python
if f.exists():
    f.unlink()
# 或：
try:
    f.unlink()
except FileNotFoundError:
    pass
```

`missing_ok=True` 一个参数解决了竞态条件（另一个进程可能抢先删了文件）和代码冗余两个问题。

---

### 技巧 7：利用 dict 插入顺序实现 LRU 淘汰

**文件**：`task_store.py:375-390`

```python
def _evict_completed(self) -> None:
    if len(self._tasks) <= self._max_tasks:
        return
    terminal = (TaskStatus.COMPLETED, TaskStatus.FAILED)
    evict_ids = [
        tid
        for tid, t in self._tasks.items()
        if t.status in terminal
    ]
    to_remove = len(self._tasks) - self._max_tasks
    for tid in evict_ids[:to_remove]:    # 取列表前 N 个（最早插入的）
        del self._tasks[tid]
```

Python 3.7+ 的 dict 保证按插入顺序迭代。`self._tasks.items()` 返回的是按插入顺序排列的键值对。

最早插入的任务在最前面，淘汰时取前 N 个（`evict_ids[:to_remove]`），实现了 FIFO（先进先出）淘汰策略。

不需要额外的 `OrderedDict` 或时间戳，利用语言特性零成本实现。

---

### 技巧 8：正则表达式处理 LLM 输出

**文件**：`llm_parse.py:8-18`

```python
_THINK_PAIR_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL)
_THINK_CLOSE_RE = re.compile(r"^.*?</think>", re.DOTALL)

def strip_think_tags(text: str) -> str:
    text = _THINK_PAIR_RE.sub("", text)   # 移除完整的 <think>...</think>
    text = _THINK_OPEN_RE.sub("", text)   # 移除只有开头没有结尾的
    text = _THINK_CLOSE_RE.sub("", text)  # 移除只有结尾没有开头的
    return text
```

`re.compile()` 预编译正则，反复使用时比每次重新编译快得多（正则编译有开销）。三个正则对应三种可能的残缺格式，处理 LLM 输出不规范的情况。

关键标志 `re.DOTALL`：让 `.` 匹配换行符（默认 `.` 不匹配 `\n`）。LLM 的 `<think>` 块通常跨越多行，必须加这个标志才能完整匹配。

`.*?` 是**非贪婪匹配**：尽可能少地匹配字符。如果不加 `?`，`.*` 会贪婪地吃掉从第一个 `<think>` 到最后一个 `</think>` 之间的所有内容（包括中间的有效输出）。

---

### 技巧 9：指数退避重试

**文件**：`llm.py:110`

```python
delay = self._retry_delay * (2 ** (attempt - 1))
# attempt=1: 2 * 2^0 = 2s
# attempt=2: 2 * 2^1 = 4s
# attempt=3: 2 * 2^2 = 8s
```

为什么不固定间隔重试（比如每次等 2 秒）？

如果 LLM 服务器因为过载而返回错误，所有客户端同时等 2 秒后再一起重试，瞬间又打出同样的流量，可能再次导致过载（**惊群效应**）。

指数退避让重试间隔越来越长，给服务器充分的恢复时间，同时多个客户端的重试时机也会因为首次请求时间不同而自然错开。

这是分布式系统里的经典模式，AWS、Google 等公有云 SDK 都用这个策略。

---

### 技巧 10：链式方法调用（Method Chaining）

**文件**：`orchestrator.py:22-24`

```python
def register(self, stage: Stage) -> "PipelineOrchestrator":
    self._stages.append(stage)
    return self           # 返回 self！
```

因为 `register()` 返回 `self`，可以链式调用：

```python
orchestrator = (
    PipelineOrchestrator()
    .register(AudioPreprocessStage(...))
    .register(ASRTranscribeStage(...))
    .register(TextCorrectionStage(...))
    .register(TranscriptBuildStage(...))
)
```

比逐行调用更紧凑，视觉上也更清楚地表达「这是一个流水线，依次注册这些 Stage」。

Python 标准库也大量使用这个模式：`str.strip().lower().split(",")`。

---

## 第十二课：Pipeline 设计模式

参考文件：`pipeline/base.py`、`pipeline/orchestrator.py`

### 12.1 问题：代码越改越乱

没有 Pipeline 时：

```python
def process(audio):
    wav = convert_to_wav(audio)
    result = run_asr(wav)
    corrected = run_correction(result)
    transcript = build_transcript(corrected)
    return transcript
```

每次需求变化都要改这个函数：加一步、删一步、调顺序、加条件跳过……函数越来越长，越来越难维护。

### 12.2 解法：把每一步变成独立的 Stage

```python
# 每个 Stage 只做一件事（单一职责）
class AudioPreprocessStage:
    name = "audio_preprocess"

    async def execute(self, ctx: PipelineContext, on_progress=None) -> PipelineContext:
        # 只负责：把音频转成 WAV
        ctx.wav_path = await convert_to_wav(ctx.audio_bytes)
        return ctx

    def should_run(self, ctx: PipelineContext) -> bool:
        return ctx.wav_path is None  # 已经有 WAV 就跳过
```

### 12.3 PipelineContext：传送带

```python
@dataclass
class PipelineContext:
    # 输入
    audio_bytes: bytes | None = None
    # 音频预处理后填入
    wav_path: Path | None = None
    # ASR 完成后填入
    asr_result: ASRResult | None = None
    # 最终输出
    transcript_entries: list[TranscriptEntry] = field(default_factory=list)
    # 记录每个 Stage 的耗时
    processing_times: dict[str, float] = field(default_factory=dict)
```

每个 Stage 从 Context 取数据，处理后把结果写回 Context，传给下一个。

### 12.4 Orchestrator：驱动引擎

```python
async def run(self, ctx: PipelineContext) -> PipelineContext:
    for stage in self._stages:
        if not stage.should_run(ctx):
            continue
        ctx = await stage.execute(ctx)
    return ctx
```

Orchestrator 的核心逻辑只有三行：遍历、判断要不要跑、执行。它不关心每个 Stage 内部做什么。

### 12.5 设计优势

```
新增需求：加 OCR 扫描步骤
→ 新建 OCRScanStage 类，在 orchestrator.register() 里加一行
→ 其他所有代码不动

删除需求：不需要人脸检测
→ 把 FaceDetectStage 的注册行删掉
→ 其他所有代码不动

条件执行：只有视频才提取关键帧
→ 在 KeyframeExtractStage.should_run() 里加条件
→ 其他所有代码不动
```

---

## 第十三课：HTTP 与 API 设计

参考文件：`routers/task.py`、`routers/upload.py`

### 13.1 HTTP 协议基础

HTTP 是浏览器和服务器的「通用语言」：

| 方法  | 含义                     | 项目用途               |
| ----- | ------------------------ | ---------------------- |
| GET   | 查询数据（不改变服务器） | 查询任务状态、下载媒体 |
| POST  | 提交数据，创建资源       | 提交转录任务           |
| PATCH | 局部更新资源             | 上传数据块（续传）     |

### 13.2 装饰器注册路由

```python
@router.post(
    "/tasks/standard_minutes",       # URL 路径
    response_model=TaskSubmitResponse, # 返回值类型
    status_code=202,                  # 成功时的状态码
)
async def submit_standard_minutes_task(
    file: UploadFile = File(...),     # 从请求体取文件
    hotwords: str | None = Form(default=None),  # 从表单取参数
    store: TaskStore = Depends(get_task_store),  # 依赖注入
) -> TaskSubmitResponse:
    ...
```

**202 Accepted 的含义**：「收到请求，已开始处理，但还没完成。」对比 200 OK（已完成）。提交任务后立刻返回 `task_id`，典型的 202 场景。

### 13.3 依赖注入

```python
store: TaskStore = Depends(get_task_store)
```

FastAPI 在调用函数前先调用 `get_task_store()` 获取 `TaskStore` 实例，再传进来。

好处：

- TaskStore 是有状态的全局单例，不应该每次请求都新建
- 测试时可以换成假的 TaskStore
- 依赖关系一眼可见

### 13.4 SHA-256 文件去重

```python
file_hash = hashlib.sha256(audio_bytes).hexdigest()
existing_id = store.lookup_by_hash(file_hash)
if existing_id:
    return TaskSubmitResponse(task_id=existing_id, existing=True)
```

SHA-256 哈希函数把任意大小的文件压缩成 64 字符的「指纹」。相同文件的指纹一定相同；不同文件的指纹几乎不可能相同（碰撞概率约 1/2^256）。

用途：用户重复上传同一文件，直接返回已有任务，0 成本。

### 13.5 分片上传：大文件的工程方案

```
客户端把 500MB 文件切成 500 块（每块 1MB）
    ↓
GET /uploads/{hash}?filename=...&total_size=...
    ← 服务端返回 offset（已收到多少字节）
    ↓
PATCH /uploads/{hash}，Header: Content-Range: bytes 0-1048575/524288000
    ↓  （重复直到全部发完）
最后一块 → 服务端校验 SHA-256 → 提交任务 → 返回 task_id
```

**断点续传**：客户端先查询 `offset`，从上次断开的位置继续发，不需要从头来。

### 13.6 RESTful 设计原则

```
资源用名词，不用动词：
  ✓ /tasks/{id}
  ✗ /getTask/{id}

操作用 HTTP 方法表达：
  GET    /tasks/{id}           查询状态
  POST   /tasks/standard_minutes  创建任务
  PATCH  /uploads/{hash}       更新（追加数据块）

层级关系用路径：
  /tasks/{id}/results   某任务的结果
  /tasks/{id}/media     某任务的媒体文件
  /tasks/{id}/frames/{filename}  某帧图像
```

### 13.7 HTTP 状态码速查

| 状态码             | 含义           | 项目场景               |
| ------------------ | -------------- | ---------------------- |
| 200 OK             | 成功           | 查询任务状态           |
| 202 Accepted       | 已接受，处理中 | 提交任务               |
| 400 Bad Request    | 请求格式错误   | Content-Range 格式错误 |
| 404 Not Found      | 资源不存在     | task_id 不存在         |
| 409 Conflict       | 冲突           | 分片偏移量不对         |
| 413 Too Large      | 文件太大       | 超过 500MB             |
| 422 Unprocessable  | 数据验证失败   | SHA-256 不匹配         |
| 500 Internal Error | 服务器内部错误 | 未捕获的异常           |

---

### 技巧 11：`async with` 互斥锁——让两个 AI 模型安全共存

**文件**：`services/model_manager.py`、`routers/synthesis.py`

RTX 2080 Ti 11GB 显存：ASR 占 4GB，TTS（ChatTTS）也占 4GB，两者不能同时加载。ModelManager 用异步上下文管理器实现互斥切换：

```python
# synthesis.py（路由层）
async with model_manager.acquire("tts"):   # 进入：若 ASR 在加载则先卸载，再加载 TTS
    result = await tts_service.synthesize_dialogue_batched(...)
# 退出 with 块：TTS 继续驻留（下次 acquire("asr") 时才懒惰卸载）
```

ModelManager 内部实现：

```python
# model_manager.py
@asynccontextmanager
async def acquire(self, model_type: str):
    async with self._lock:                 # asyncio.Lock：排他锁，同一时刻只有一个任务进入
        if model_type not in self._loaded_models:
            await self._do_unload_all_except(model_type)   # 卸载其他模型 + 清空显存
            await self._do_load(model_type)                # 加载目标模型
    yield                                  # 把控制权还给调用方（执行 with 块内部代码）
    # 退出后不立刻卸载：模型继续驻留，下次 acquire 时懒惰卸载
```

`asyncio.Lock` 是排他锁：多个请求同时触发 TTS 合成时，只有第一个能进入，其他请求等待。等待期间不阻塞事件循环，其他异步任务照常运行——这是和 `threading.Lock` 的根本区别。

**懒惰卸载策略**：TTS 合成后不立刻卸载，让模型驻留等待下次合成请求。下次有人 `acquire("asr")` 时才把 TTS 卸掉。避免了「合成→立刻卸载→立刻重新合成→再卸载」的反复显存倒腾开销。

`@asynccontextmanager` 把普通 `async def` + `yield` 的生成器函数变成上下文管理器，`yield` 之前是「进入」，`yield` 之后是「退出」，`yield` 本身是暂停点。这和第九课的 `_task_lifecycle` 用的是同一个技术。

---

## 项目架构全景图

读完全部课程，用一张图串联所有知识：

```
用户上传音频（浏览器）
    ↓ HTTP POST /tasks/standard_minutes（小文件）
    ↓ GET /uploads/{hash} + PATCH /uploads/{hash}（大文件分片）
路由层（routers/task.py / routers/upload.py）        ← 第十三课
    → @router.post 注册路由
    → hashlib.sha256() 文件去重
    → Depends(get_task_store) 依赖注入
    → store.submit_standard_minutes()
    ↓
任务调度层（task_store.py）               ← 第十课 + 第十一课
    → uuid.uuid4().hex 生成唯一 ID        ← 技巧 7
    → asyncio.create_task() 后台执行      ← 第十课
    → asyncio.wait_for() 超时保护         ← 第十课
    ↓
流水线层（pipeline/orchestrator.py）      ← 第十二课 + 第十一课
    → PipelineOrchestrator.run()          ← 第十二课
    → stage.should_run() 条件跳过         ← 第七课 Protocol
    → _make_cb() 工厂函数防闭包陷阱       ← 技巧 1
    → time.perf_counter() 计时            ← 技巧 4
    ↓
各处理阶段（pipeline/stages/）            ← 第七课 Stage Protocol
    → @dataclass PipelineContext 传送带   ← 第六课
    → field(default_factory=list) 安全    ← 技巧（第六课 6.5）
    ↓
LLM 客户端（llm.py）                     ← 第四课 + 第十课
    → asyncio.Semaphore 并发限制          ← 第十课
    → 指数退避重试                        ← 技巧 9
    → @dataclass(frozen=True) 不可变消息  ← 第六课
    ↓
数据模型（schemas/task.py）               ← 第二课 + 第七课
    → TaskStatus(StrEnum) 状态机          ← 第七课
    → TaskProgress(BaseModel) 数据验证    ← 第二课
    ↓
配置中心（config.py）                     ← 第一课
    → Settings(BaseSettings) 集中配置
    → @property 计算属性                  ← 第八课
    → os.cpu_count() or 8 空值默认        ← 技巧 2
    ↓
前端轮询结果，渲染转录稿、报告

━━━ 音频重塑分支（转写完成后按需触发）━━━

用户点击"合成对话音频"
    ↓ HTTP POST /tasks/{id}/synthesize
路由层（routers/synthesis.py）
    → 从 TaskStore 取出转录结果
    → 调用 services/tts.py
    ↓
模型管理层（services/model_manager.py）   ← 技巧 11
    → async with acquire("tts") 排他锁
    → ASR 模型自动卸载，释放 VRAM
    → ChatTTS 懒加载（load_chattts）
    ↓
TTS 合成层（services/tts.py）
    → 说话人→音色种子映射
    → 分批合成（TTS_SYNTHESIS_BATCH_CHARS），批间清显存
    → concat_parts_to_mp3() 拼接输出
    ↓
持久化（data/{task_id}/synthesis.mp3）
    ↓ GET /tasks/{id}/synthesis 流式下载
前端 SynthesisPanel 检测 has_synthesis，自动展开播放器
```

每一层职责单一，层与层之间通过明确的接口交互。这就是**分层架构**的核心价值：修改一层，不影响其他层。
