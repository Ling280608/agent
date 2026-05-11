import json
import os
import uuid
from http import HTTPStatus
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from dashscope import MultiModalConversation
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, ToolMessage, convert_to_messages, convert_to_openai_messages
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph._internal._config import ensure_config, patch_configurable
from langgraph._internal._constants import CONFIG_KEY_RUNTIME
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.runtime import DEFAULT_RUNTIME
from pydantic import BaseModel, Field, model_validator

from scripts.langchain_openai_reasoning_patch import apply_langchain_openai_reasoning_content_patch

# 须在实例化 ChatOpenAI 之前执行（实现langchain PR #35065 一致：保留 reasoning_content）
apply_langchain_openai_reasoning_content_patch()

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# LangGraph 单轮内 agent↔tools 最大往返次数（每次 tools 后再 agent 记 1）
_CHAT_RECURSION_LIMIT = 30


def _api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")


def _create_agent_llm() -> ChatOpenAI:
    """图中节点用 invoke，streaming=False 即可。"""
    return ChatOpenAI(
        model="qwen3.6-plus",
        base_url=DASHSCOPE_BASE_URL,
        api_key=_api_key(),
        temperature=0,
        streaming=True,
    )


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
    return "\n".join(urls)


QWEN_IMAGE_TOOLS = [qwen_image_generate]

_AGENT_LLM = _create_agent_llm().bind_tools(QWEN_IMAGE_TOOLS)


CHAT_TOOL_NODE = ToolNode(QWEN_IMAGE_TOOLS)


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def _agent_node(state: AgentState) -> dict[str, list]:
    response = _AGENT_LLM.invoke(state["messages"])
    return {"messages": [response]}


def _route_tools(state: AgentState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


def _build_chat_graph():
    b = StateGraph(AgentState)
    b.add_node("agent", _agent_node)
    b.add_node("tools", CHAT_TOOL_NODE)
    b.add_edge(START, "agent")
    b.add_conditional_edges("agent", _route_tools, {"tools": "tools", END: END})
    b.add_edge("tools", "agent")
    return b.compile()


CHAT_GRAPH = _build_chat_graph()

_MAX_IMAGES_PER_REQUEST = 4
_MAX_DATA_URL_LEN = 6_500_000

def _validate_image_url(url: str) -> str:
    """验证传来的图片 URL 是否合法"""
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
    SSE：LangGraph（agent ↔ tools）驱动；事件含 session、thinking、token、tool_result、done。
    会话存 OpenAI 风格消息列表，与 convert_to_messages / convert_to_openai_messages 对齐。
    """

    def event_stream():
        # SSE：每行以 "data: " 开头；连续两个换行表示「一条事件」结束（须先于可能 yield error 的分支定义）
        def sse(obj: dict) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

        # 1) 确定会话：无 session_id 则新建 UUID，后续请求带同一 id 即续聊
        session_id = req.session_id or str(uuid.uuid4())
        history = _SESSIONS.get(session_id)
        if history is None:
            history = []
            _SESSIONS[session_id] = history

        # 2) 本轮用户消息：纯文本或多模态（与通义 OpenAI 兼容格式一致），写入会话供后续轮次使用
        try:
            user_msg = _build_user_message(req.message, req.images)
        except ValueError as ve:
            yield sse({"event": "error", "detail": str(ve)})
            return

        messages_dicts = [*history, user_msg]

        try:
            lc_messages = convert_to_messages(messages_dicts)
        except Exception as e:
            yield sse({"event": "error", "detail": f"消息解析失败: {e}"})
            return

        yield sse({"event": "session", "session_id": session_id})

        # 本轮可变的 LangChain 消息列表（含历史 + 本回合用户消息）；流式循环内就地追加 AI / ToolMessage
        working_msgs = list(lc_messages)

        try:
            # 与 CHAT_GRAPH 相同的 agent ↔ tools 上限；每轮先 stream 再决定是否进 ToolNode
            for _ in range(_CHAT_RECURSION_LIMIT):
                # 通义 reasoning_content 在流式里可能为「累计字符串」，用前缀差分避免重复推送
                last_rc = ""
                acc = None
                
                # 流式输出内容
                for chunk in _AGENT_LLM.stream(working_msgs):
                    acc = chunk if acc is None else acc + chunk
                    ak = chunk.additional_kwargs or {}
                    rc = ak.get("reasoning_content")
                    if rc and isinstance(rc, str):
                        if rc.startswith(last_rc):
                            delta = rc[len(last_rc) :]
                            last_rc = rc
                            if delta:
                                yield sse({"event": "thinking", "text": delta})
                        else:
                            last_rc = rc
                            yield sse({"event": "thinking", "text": rc})
                    c = chunk.content
                    if c:
                        text = c if isinstance(c, str) else str(c)
                        if text:
                            yield sse({"event": "token", "text": text})

                if acc is None:
                    break

                # 将流式块上的 tool_call_chunks 规整为 tool_calls，便于 ToolNode 与 OpenAI 互转
                acc.init_tool_calls()
                ai_msg = AIMessage(
                    content=acc.content,
                    tool_calls=list(acc.tool_calls or []),
                    additional_kwargs=dict(acc.additional_kwargs or {}),
                    response_metadata=dict(acc.response_metadata or {}),
                )
                working_msgs.append(ai_msg)

                if not ai_msg.tool_calls:
                    break

                # LangGraph 1.1+ 的 ToolNode 需要注入 runtime；仅在编译图内跑节点时 Pregel 会写入 __pregel_runtime。
                # SSE 手写循环在图外 invoke，若不补 DEFAULT_RUNTIME，会报 Missing required config key 'N/A' for 'tools'。
                _tn_cfg = patch_configurable(
                    ensure_config(),
                    {CONFIG_KEY_RUNTIME: DEFAULT_RUNTIME},
                )
                tool_out = CHAT_TOOL_NODE.invoke(
                    {"messages": working_msgs},
                    config=_tn_cfg,
                )
                for tm in tool_out["messages"]:
                    working_msgs.append(tm)
                    if isinstance(tm, ToolMessage):
                        yield sse(
                            {
                                "event": "tool_result",
                                "tool_call_id": tm.tool_call_id,
                                "name": tm.name or "",
                                "content": tm.content if isinstance(tm.content, str) else str(tm.content)
                            }
                        )

            _SESSIONS[session_id] = convert_to_openai_messages(working_msgs)
            yield sse({"event": "done"})
        except Exception as e:
            yield sse({"event": "error", "detail": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
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
