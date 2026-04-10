import os
import uuid
from pathlib import Path
from typing import Annotated, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from langchain_openai import ChatOpenAI
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class State(TypedDict):
    # LangGraph 的“状态”结构：
    # - 我们用 messages 作为对话上下文（list[message]）
    # - add_messages 会把节点返回的新消息“追加”到历史里，而不是覆盖
    messages: Annotated[list, add_messages]


def build_graph() -> "langgraph.graph.state.CompiledStateGraph":  # type: ignore[name-defined]
    # 1) 初始化大模型客户端
    # 这里使用 DashScope 的 OpenAI 兼容接口（也支持你自建的 OpenAI compatible 网关）
    # - QWEN_MODEL：模型名
    # - OPENAI_BASE_URL：兼容网关地址（DashScope 示例已给默认）
    # - OPENAI_API_KEY / DASHSCOPE_API_KEY：二选一
    llm = ChatOpenAI(
        model="qwen3.6-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key=os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY"),
        temperature=float(os.getenv("TEMPERATURE", "0")),
    )

    # 2) 构建 LangGraph：本例是最简图（START -> chatbot）
    graph_builder = StateGraph(State)

    def chatbot(state: State):
        # 节点函数：把当前对话 messages 丢给 LLM，让它生成一条 AI 回复
        # 返回值必须是“对 State 的增量更新”，这里是新增一条 messages
        return {"messages": [llm.invoke(state["messages"])]}

    graph_builder.add_node("chatbot", chatbot)
    graph_builder.add_edge(START, "chatbot")
    return graph_builder.compile()


# 启动时就把图编译好，后续每次请求直接复用（避免每个请求都重新构建图）
GRAPH = build_graph()



# 会话存储（内存版）：
# - key: session_id
# - value: 该会话的消息列表（用户/助手的历史）
# 适合本地 demo；生产环境建议换 Redis / 数据库，且需要做过期/清理策略。
_SESSIONS: Dict[str, List[dict]] = {}


class ChatRequest(BaseModel):
    # 前端发来的请求体
    message: str = Field(min_length=1, max_length=8000)
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    # 返回给前端：session_id 用于继续同一轮对话；assistant 为本次回答文本
    session_id: str
    assistant: str


app = FastAPI(title="Agent Web")

# 3) 静态页面托管：复用 `web/static/` 的前端资源
repo_root = Path(__file__).resolve().parents[1]
static_dir = repo_root / "web" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
def index():
    # 主页：返回聊天 UI 页面
    return FileResponse(str(static_dir / "index.html"))


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    # 如果有session_id，则使用session_id，否则生成一个新的session_id
    session_id = req.session_id or str(uuid.uuid4())

    # 获取会话历史；没有就初始化
    messages = _SESSIONS.get(session_id)
    if messages is None:
        messages = []
        _SESSIONS[session_id] = messages

    # 把本次用户输入追加进上下文（role/content 是 OpenAI 风格消息）
    messages.append({"role": "user", "content": req.message})

    try:
        # 调用图执行：输入是 {"messages": 历史}，输出会包含追加后的 messages
        result = GRAPH.invoke({"messages": messages})
    except Exception as e:
        # 统一转成 500，方便前端展示错误信息
        raise HTTPException(status_code=500, detail=str(e)) from e

    # 取最后一条消息作为本次 AI 回复
    assistant_msg = result["messages"][-1]
    assistant_text = getattr(assistant_msg, "content", str(assistant_msg))
    # 把助手回复也写回会话历史，保证下一轮对话有上下文
    messages.append({"role": "assistant", "content": assistant_text})

    return ChatResponse(session_id=session_id, assistant=assistant_text)

