from pathlib import Path

from langchain_core.messages import AnyMessage
from typing_extensions import TypedDict
from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph
from langgraph.prebuilt import create_react_agent

#定义节点间通讯的消息格式
class State(TypedDict):
    messages:list[AnyMessage]
    extra_field:int


def node(state:State)->State:
    messages = state['messages']
    new_message = AIMessage("你好!我是节点1")
    
    return {
    "messages": messages + [new_message],
    "extra_field":1
    }



graph = StateGraph(State)
graph.add_node(node)
graph.set_entry_point ("node")
graph_builder = graph.compile()

# draw_mermaid_png() 返回 PNG 二进制，不是 URL；写入文件后即可用看图软件 / 浏览器打开
chart = graph_builder.get_graph()
out_path = Path(__file__).with_name("langchain_graph.png")
out_path.write_bytes(chart.draw_mermaid_png())
print(f"流程图已保存: {out_path.resolve()}")

# 可选：在 Jupyter 里嵌图  from IPython.display import Image; display(Image(data=chart.draw_mermaid_png()))