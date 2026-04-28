import os
import sys
from pathlib import Path

# 保证从 test/ 子目录直接运行时能 import 仓库根目录下的补丁模块
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from langchain_openai import ChatOpenAI

from scripts.langchain_openai_reasoning_patch import apply_langchain_openai_reasoning_content_patch

# 须在实例化 ChatOpenAI 之前执行（实现langchain PR #35065 一致：保留 reasoning_content）
apply_langchain_openai_reasoning_content_patch()

llm = ChatOpenAI(
    model="qwen3.6-plus",
    api_key=os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    streaming=True,
)

def main() -> None:
    full_reasoning: list[str] = []
    full_text: list[str] = []
    for chunk in llm.stream("请用简短步骤推理：9.9 和 9.11 哪个大？"):
        # 流式：reasoning_content 在 additional_kwargs；langchain_core 合并 chunk 时对 str 做 += 拼接
        ak = getattr(chunk, "additional_kwargs", None) or {}
        rc = ak.get("reasoning_content")
        if rc:
            print()
            full_reasoning.append(rc)
            print(f"思考片段: {rc}", end="", flush=True)
        c = chunk.content
        if c:
            if isinstance(c, str):
                full_text.append(c)
                print(f"正文: {c}", end="", flush=True)
            # elif isinstance(c, list):
            #     for block in c:
            #         if not isinstance(block, dict):
            #             continue
            #         if block.get("type") in ("reasoning", "thinking"):
            #             t = block.get("reasoning") or block.get("thinking") or ""
            #             if t:
            #                 print(t, end="", flush=True)
            #         elif block.get("type") == "text":
            #             print(block.get("text", ""), end="", flush=True)
    print()
    print("---")
    print("reasoning 总长:", len("".join(full_reasoning)))
    print("正文总长:", len("".join(full_text)))

if __name__ == "__main__":
    main()
