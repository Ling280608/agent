"""
聊天 API：FastAPI + LangChain（ChatOpenAI 配置）+ 通义兼容流式。

为何「思考」不能只用 LLM.stream()：
  LangChain 的 ChatOpenAI 在把 OpenAI 兼容接口的流式 chunk 转成 AIMessageChunk 时，
  只解析标准字段 content，不会把第三方扩展字段（如通义/DashScope 的 reasoning_content）
  写进 chunk，因此 enable_thinking=true 时思考文本在 LangChain 流式路径里拿不到。

做法：
  SSE 仍用官方 openai 库的 chat.completions.create(stream=True)，直接读 delta 上的
  reasoning_content 与 content，分别推 thinking / token 事件；模型参数与 ChatOpenAI 对齐。
"""

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field, model_validator

from langchain_openai import ChatOpenAI

# --- 与网关、模型相关的环境变量（流式客户端与 ChatOpenAI 共用） ---
CHAT_MODEL = "qwen3.6-plus"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _api_key() -> str | None:
    # 兼容两种常见命名：OpenAI 系与阿里云 DashScope
    return os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")


def _enable_thinking() -> bool:
    # 为 True 时请求体会带 enable_thinking，模型才可能返回 reasoning_content
    return True


def create_llm() -> ChatOpenAI:
    """与流式 OpenAI 客户端共用同一套 endpoint/model，便于在非流式场景用 LangChain API。"""
    kwargs: dict[str, Any] = {
        "model": CHAT_MODEL,
        "base_url": DASHSCOPE_BASE_URL,
        "api_key": _api_key(),
        "temperature": 0,
    }
    # 通义兼容接口的扩展参数需放在 extra_body，不能混进标准 OpenAI 顶层字段
    if _enable_thinking():
        kwargs["extra_body"] = {"enable_thinking": True}
    return ChatOpenAI(**kwargs)


# 进程内单例：供 invoke / 链式编排等非 SSE 场景使用
LLM = create_llm()

# SSE 必须用「原始」OpenAI SDK：LangChain 流式不会透出 reasoning_content
_STREAM_CLIENT: OpenAI | None = None

def _stream_openai_client() -> OpenAI:
    """流式 OpenAI 客户端：单例，供 SSE 流式使用"""
    global _STREAM_CLIENT
    if _STREAM_CLIENT is None:
        _STREAM_CLIENT = OpenAI(base_url=DASHSCOPE_BASE_URL, api_key=_api_key())
    return _STREAM_CLIENT


def _delta_reasoning(delta: Any) -> str:
    """从流式 delta 取思考片段（厂商字段名可能为 reasoning_content 或 thinking）。"""
    if delta is None:
        return ""
    if isinstance(delta, dict):
        for name in ("reasoning_content", "thinking"):
            v = delta.get(name)
            if v:
                return v if isinstance(v, str) else str(v)
        return ""
    for name in ("reasoning_content", "thinking"):
        v = getattr(delta, name, None)
        if v:
            return v if isinstance(v, str) else str(v)
    return ""


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

        try:
            # 3) 首包带上 session_id，前端可立即保存，不必等流结束
            yield sse({"event": "session", "session_id": session_id})
            answer_pieces: List[str] = []
            create_kw: dict[str, Any] = {
                "model": CHAT_MODEL,
                "messages": messages,
                "stream": True,
            }
            if _enable_thinking():
                create_kw["extra_body"] = {"enable_thinking": True}
            # 4) 建立流式连接；messages 中最后一条已是当前 user，模型在此基础上续写 assistant
            stream = _stream_openai_client().chat.completions.create(**create_kw)
            for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue
                # 5) 同一 chunk 可能只有思考、只有正文、或两者都有，分支独立 yield
                think = _delta_reasoning(delta)
                if think:
                    yield sse({"event": "thinking", "text": think})
                ans = _delta_answer(delta)
                if ans:
                    answer_pieces.append(ans)
                    yield sse({"event": "token", "text": ans})
            # 流结束：拼接正文写入会话，供下一轮多轮对话；思考内容不写入 messages（避免回传模型）
            assistant_text = "".join(answer_pieces)
            messages.append({"role": "assistant", "content": assistant_text})
            yield sse({"event": "done"})
        except Exception as e:
            # 响应头已是 200 且 body 为事件流，错误用 error 事件传出，前端统一展示
            yield sse({"event": "error", "detail": str(e)})

    # Starlette 会迭代生成器：每次 yield 的字节块立刻发往客户端，实现打字机效果
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
