from langchain.agents import create_agent
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
import os

def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"It's always sunny in {city}!"

# 本地ollama模型
# llm = ChatOllama(
#   model="qwen3.5:9b",                  # 改成你的实际模型名
#   base_url="http://192.168.2.207:11434" # 改成局域网服务器IP
# )

llm = ChatOpenAI(
    model="qwen3.6-plus",          # 按你的服务端实际模型名改
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",              # 你的千问网关（OpenAI兼容）地址，形如 https://xxx/v1
    api_key=os.getenv("DASHSCOPE_API_KEY")
    )

agent = create_agent(
    model=llm,
    tools=[get_weather]
)

# Run the agent
result = agent.invoke(
    {"messages": [{"role": "user", "content": "what is the weather in sf"}]}
)
print(result.get("messages")[-1].content)