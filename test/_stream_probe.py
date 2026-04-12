"""探针：在配置了 OPENAI_API_KEY 或 DASHSCOPE_API_KEY 时，打印 LangGraph 多模式 stream 的事件形状。

说明：langchain_core 已无 FakeStreamingChatModel，故用真实 ChatOpenAI（与 server/main 同 base_url）做最小图探测。
"""
import os
from typing import Annotated

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class S(TypedDict):
    messages: Annotated[list, add_messages]


def _key() -> str | None:
    return os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")


def main() -> None:
    key = _key()
    if not key:
        print("skip: 未设置 OPENAI_API_KEY / DASHSCOPE_API_KEY")
        return

    llm = ChatOpenAI(
        model="qwen3.6-plus",
        base_url=DASHSCOPE_BASE_URL,
        api_key=key,
        temperature=0,
        streaming=True,
    )

    def agent(state: S) -> dict:
        return {"messages": [llm.invoke(state["messages"])]}

    b = StateGraph(S)
    b.add_node("agent", agent)
    b.add_edge(START, "agent")
    b.add_edge("agent", END)
    g = b.compile()

    for item in g.stream(
        {"messages": [HumanMessage("只回复一个字：好")]},
        stream_mode=["messages", "values"],
    ):
        print("ITEM", type(item), repr(item)[:500])


if __name__ == "__main__":
    main()
