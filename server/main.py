import json
import os
import sys
import uuid
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, List, Optional
from dashscope import MultiModalConversation
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field, model_validator
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai import ChatOpenAI

from scripts.langchain_openai_reasoning_patch import apply_langchain_openai_reasoning_content_patch

# 须在实例化 ChatOpenAI 之前执行（实现langchain PR #35065 一致：保留 reasoning_content）
apply_langchain_openai_reasoning_content_patch()

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _api_key() -> str | None:
    # 兼容两种常见命名：OpenAI 系与阿里云 DashScope
    return os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")


def create_llm() -> ChatOpenAI:
    """与流式 OpenAI 客户端共用同一套 endpoint/model，便于在非流式场景用 LangChain API。"""
    kwargs: dict[str, Any] = {
        "model": "qwen3.6-plus",
        "base_url": DASHSCOPE_BASE_URL,
        "api_key": _api_key(),
        "temperature": 0,
        "streaming": True,
    }
    
    return ChatOpenAI(**kwargs)


def _call_qwen_image_api(prompt: str, size: str = "1024*1024", n: int = 1) -> list[str]:
    """通过 DashScope SDK（MultiModalConversation）调用同步文生图，返回 PNG 临时 URL 列表。"""
    key = _api_key()
    if not key:
        raise ValueError("未配置 OPENAI_API_KEY 或 DASHSCOPE_API_KEY")
    text = (prompt or "").strip()
    if not text:
        raise ValueError("文生图提示词不能为空")
    if len(text) > 800:
        text = text[:800]
    n = max(1, min(6, int(n)))
    # 与控制台示例一致：单轮 messages + parameters（SDK 将额外关键字写入请求体 parameters）
    rsp = MultiModalConversation.call(
        model="qwen-image-2.0",
        api_key=key,
        messages=[
            {
                "role": "user",
                "content": [{"text": text}],
            }
        ],
        size=size,
        n=n,
        watermark=False,
        request_timeout=180,
    )
    if rsp.status_code != HTTPStatus.OK:
        raise RuntimeError(getattr(rsp, "message", None) or f"HTTP {rsp.status_code}")
    if getattr(rsp, "code", None):
        raise RuntimeError(getattr(rsp, "message", None) or str(rsp.code))
    output = getattr(rsp, "output", None)
    if output is None:
        raise RuntimeError("文生图无 output: " + str(rsp)[:800])
    choices = output.get("choices") if isinstance(output, dict) else getattr(output, "choices", None)
    if not choices:
        raise RuntimeError("文生图 output 无 choices: " + str(rsp)[:800])
    urls: list[str] = []
    for ch in choices:
        msg = ch.get("message") if isinstance(ch, dict) else getattr(ch, "message", None)
        if msg is None:
            continue
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        if not content:
            continue
        for part in content:
            if isinstance(part, dict):
                u = part.get("image")
                if u:
                    urls.append(u if isinstance(u, str) else str(u))
    if not urls:
        raise RuntimeError("文生图未返回图片地址: " + str(rsp)[:800])
    return urls


@tool
def qwen_image_generate(prompt: str, size: str = "1024*1024", n: int = 1) -> str:
    """使用 Qwen-Image-2.0 根据文字描述生成 PNG 图片（返回临时 URL，请在有效期内下载）。
    当用户需要插画、海报、概念图、配图、文生图、画一张图、生成示意图时调用。
    prompt: 画面内容、风格、构图的中英文描述（约 800 字内）。
    size: 分辨率 宽*高，如 1024*1024、2048*2048、2688*1536（16:9）、1536*2688（9:16）。
    n: 生成张数 1～6。
    """
    urls = _call_qwen_image_api(prompt, size=size, n=n)
    print(f"图片URL: {urls}")
    return "\n".join(urls)


# 供 LangGraph ToolNode 等与 bind_tools 使用同一份工具定义
QWEN_IMAGE_TOOLS = [qwen_image_generate]


# 在 ChatOpenAI 上绑定 Qwen-Image-2.0 文生图工具
LLM = create_llm().bind_tools(QWEN_IMAGE_TOOLS)

# SSE 用「原始」OpenAI SDK 读 delta.reasoning_content；若用 LLM.stream()，需依赖上方 reasoning 补丁
_STREAM_CLIENT: OpenAI | None = None

# 从流式 delta 取思考片段（厂商字段名可能为 reasoning_content 或 thinking）
def _delta_reasoning(delta: Any) -> str:
    """从流式 delta 取思考片段（厂商字段名可能为 reasoning_content 或 thinking）。"""
    if delta is None:
        return ""
    ak = getattr(delta, "additional_kwargs", None) or {}
    rc = ak.get("reasoning_content")
    if rc:
        return rc if isinstance(rc, str) else str(rc)
    return ""

# 从流式 delta 取对用户可见的正文增量（标准 content 字段）
def _delta_answer(delta: Any) -> str:
    """从流式 delta 取对用户可见的正文增量（标准 content 字段）。"""
    if delta is None:
        return ""
    if isinstance(delta, dict):
        c = delta.get("content")
    else:
        c = getattr(delta, "content", None)
    if not c:
        return ""
    return c if isinstance(c, str) else str(c)


# 多模态：单图 base64 体积上限（字符数，约对应数 MB 原图）
_MAX_IMAGES_PER_REQUEST = 4
_MAX_DATA_URL_LEN = 6_500_000

# 验证传来的图片 URL 是否合法
def _validate_image_url(url: str) -> str:
    """
    接受：
    - data:image/<subtype>;base64,<data>（浏览器 FileReader 典型产物）
    - http(s) 公网图链（若网关支持）
    """
    u = (url or "").strip()
    if not u:
        raise ValueError("图片地址为空")
    if u.startswith(("http://", "https://")):
        return u
    if not u.startswith("data:image/"):
        raise ValueError("图片须为 data:image/...;base64,... 或 http(s) URL")
    if ";base64," not in u:
        raise ValueError("data URL 须包含 ;base64,")
    if len(u) > _MAX_DATA_URL_LEN:
        raise ValueError("单张图片过大，请压缩或缩小尺寸后重试")
    return u

# 创建用户消息
def _build_user_message(message: str, images: Optional[List[str]]) -> dict[str, Any]:
    """
    纯文本：OpenAI 风格 {"role":"user","content":"..."}。
    含图：content 为部件列表，与 DashScope 兼容多模态一致：
      [{"type":"image_url","image_url":{"url":...}}, {"type":"text","text":...}]
    图片在前、文字在后，便于视觉模型先看图再看指令。
    """
    imgs = [_validate_image_url(x) for x in (images or [])]
    text = (message or "").strip()
    if not imgs:
        return {"role": "user", "content": text}
    parts: List[dict[str, Any]] = []
    for u in imgs:
        parts.append({"type": "image_url", "image_url": {"url": u}})
    parts.append({"type": "text", "text": text or "请根据图片回答。"})
    return {"role": "user", "content": parts}


# key：前端回传的 session_id；value：OpenAI 风格 messages（content 可为 str 或多模态 list）
_SESSIONS: Dict[str, List[dict]] = {}

# 消息结构体
class ChatRequest(BaseModel):
    """message 与 images 至少其一；images 为 data URL 或 http(s) 链接列表。"""

    message: str = Field(default="", max_length=8000)
    images: Optional[List[str]] = Field(default=None, max_length=_MAX_IMAGES_PER_REQUEST)
    session_id: Optional[str] = None

    @model_validator(mode="after")
    def at_least_text_or_image(self) -> "ChatRequest":
        has_text = bool(self.message and self.message.strip())
        imgs = self.images or []
        if not has_text and not imgs:
            raise ValueError("请至少发送文字或一张图片")
        if len(imgs) > _MAX_IMAGES_PER_REQUEST:
            raise ValueError(f"最多上传 {_MAX_IMAGES_PER_REQUEST} 张图片")
        return self


# FastAPI 应用
app = FastAPI(title="Agent Web")


@app.post("/api/chat")
def chat(req: ChatRequest):
    """
    SSE：session →（可选）thinking → token（正文）→ done。
    思考链走原生流式 delta；会话仍为 OpenAI 风格 messages 列表。
    """

    def event_stream():
        # SSE：每行以 "data: " 开头；连续两个换行表示「一条事件」结束（须先于可能 yield error 的分支定义）
        def sse(obj: dict) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

        # 1) 确定会话：无 session_id 则新建 UUID，后续请求带同一 id 即续聊
        session_id = req.session_id or str(uuid.uuid4())
        messages = _SESSIONS.get(session_id)
        if messages is None:
            messages = []
            _SESSIONS[session_id] = messages

        # 2) 本轮用户消息：纯文本或多模态（与通义 OpenAI 兼容格式一致），写入会话供后续轮次使用
        try:
            user_msg = _build_user_message(req.message, req.images)
        except ValueError as ve:
            yield sse({"event": "error", "detail": str(ve)})
            return
        messages.append(user_msg)

        full_message = None
        try:
            # 3) 首包带上 session_id，前端可立即保存，不必等流结束
            yield sse({"event": "session", "session_id": session_id})
            client = LLM
            for chunk in client.stream(messages):
                if full_message is None:
                    full_message = chunk
                else:
                    full_message += chunk
                think = _delta_reasoning(chunk)
                print(f"思考片段: {think}")
                if think:
                    yield sse({"event": "thinking", "text": think})
                ans = _delta_answer(chunk)
                if ans:
                    print(f"正文: {ans}")
                    yield sse({"event": "token", "text": ans})
            yield sse({"event": "done"})
            print(f"full_message: {full_message}")
        except Exception as e:
            yield sse({"event": "error", "detail": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 关闭反向代理对响应体的缓冲，否则 SSE 会整块延迟到达浏览器
            "X-Accel-Buffering": "no",
        },
    )

# 仓库根下的 web/static → 挂到 /static，供 HTML 引用 CSS/JS/图标
repo_root = Path(__file__).resolve().parents[1]
static_dir = repo_root / "web" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
def index():
    # 根路径直接返回单页，由其中脚本请求 /api/chat
    return FileResponse(str(static_dir / "index.html"))
