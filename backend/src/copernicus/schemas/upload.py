from pydantic import BaseModel


class UploadQueryResponse(BaseModel):
    offset: int = 0          # 已接收字节数；complete=True 时等于 total_size
    complete: bool = False   # True = 文件已处理完成
    task_id: str | None = None


class UploadChunkResponse(BaseModel):
    received: int            # 服务端已接收的总字节数
    complete: bool
    task_id: str | None = None  # 仅最后一块完成时有值
