from langchain.agents import create_agent
from langchain_ollama import ChatOllama

def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"It's always sunny in {city}!"

llm = ChatOllama(
  model="qwen3.5:9b",                  # 改成你的实际模型名
  base_url="http://192.168.2.207:11434" # 改成局域网服务器IP
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