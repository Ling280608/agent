from langchain_tavily import TavilySearch
from langchain_openai import ChatOpenAI
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.graph import END
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
import os

class State(TypedDict):
    # 对话状态：messages 会在每次节点执行后“追加”，而不是被覆盖。
    # add_messages 是 LangGraph 提供的状态合并策略。
    messages: Annotated[list, add_messages]


# 1) 先定义状态机（图）结构
graph_builder = StateGraph(State)


# 2) 初始化模型客户端（这里使用 DashScope 的 OpenAI 兼容接口）
llm = ChatOpenAI(
    model="qwen3.6-plus",          # 按你的服务端实际模型名改             
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", # 你的千问网关（OpenAI兼容）地址，形如 https://xxx/v1
    api_key=os.getenv("DASHSCOPE_API_KEY")
    )

@tool
def weather_tool(city: str) -> str:
    """获取一个城市的天气情况."""
    return f"{city} 很不错!"

tavily = TavilySearch(max_results=2)
tools = [weather_tool]

llm = llm.bind_tools(tools)

def chatbot(state: State):
    print("state:", state["messages"])
    # 节点函数：读取当前 messages，调用 LLM，返回新增的一条 AI 消息。
    response = llm.invoke(state["messages"])
    print("response:", response)
    return {"messages": [response]}


def route_tools(state: State):
    last = state["messages"][-1]
    # 如果模型输出里带 tool_calls，就去执行工具；否则结束
    if getattr(last, "tool_calls", None):
        return "tools"
    return END



tool_node = ToolNode(tools)
graph_builder.add_node("tools", tool_node)

# 3) 注册节点，并把 START 连接到 chatbot，表示图从这里开始执行
graph_builder.add_node("chatbot", chatbot)

graph_builder.add_edge(START, "chatbot")
graph_builder.add_conditional_edges("chatbot", route_tools, {"tools": "tools", END: END})
graph_builder.add_edge("tools", "chatbot")

# 4) 编译图，得到可执行对象
graph = graph_builder.compile()



def stream_graph_updates(user_input: str):
    # graph.stream开始图的执行，并传入用户输入数据，数据开始流转
    for event in graph.stream({"messages": [{"role": "user", "content": user_input}]}):
        #  event为一个流程下来每个节点node返回的数据字典
        print("event:", event)
        for value in event.values():
            # 取出这个节点返回数据所有值中包含messages属性的数据，取出messages属性中最后一个消息的content并输出
            print("Assistant:", value["messages"][-1].content)

# 5) 一个简单 CLI 循环：读取输入 -> 调图 -> 输出
while True:
    try:
        user_input = input("User: ")
        if user_input.lower() in ["quit", "exit", "q"]:
            print("Goodbye!")
            break
        stream_graph_updates(user_input)
    except:
        # 某些环境下 input() 不可用时，给一个默认问题做降级演示
        user_input = "What do you know about LangGraph?"
        print("User: " + user_input)
        stream_graph_updates(user_input)
        break


