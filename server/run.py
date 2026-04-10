"""
从 `config.yaml` 读取 host/port/reload，然后启动 Uvicorn。

这份文件刻意写得“新手友好”一些（特别是 Java 转 Python 的同学）：
- 先找到项目根目录
- 读取 YAML 配置
- 提供合理默认值（即使配置缺字段也能启动）
- 最后启动 uvicorn
"""

from __future__ import annotations
import os
import sys
from pathlib import Path
import uvicorn
import yaml


def main() -> None:
    # 1) 定位项目根目录：`.../server/run.py` 的上上级目录就是仓库根目录
    repo_root = Path(__file__).resolve().parents[1]

    # 2) 读取 config.yaml（如果文件不存在，就用空 dict）
    cfg_path = repo_root / "config.yaml"
    cfg = {}
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    # 3) 拿到 server 配置块（你的 config.yaml 形如：
    #    server:
    #      host: "127.0.0.1"
    #      port: 8000
    #      reload: true
    #      app: "server.main:app"
    # )
    server_cfg = cfg.get("server", {}) if isinstance(cfg, dict) else {}
    if not isinstance(server_cfg, dict):
        server_cfg = {}

    # 4) 逐项取配置 + 默认值（也支持用环境变量覆盖）
    app = str(server_cfg.get("app", "server.main:app"))
    host = str(server_cfg.get("host", os.getenv("HOST", "127.0.0.1")))
    port = int(server_cfg.get("port", os.getenv("PORT", "8000")))
    reload = bool(server_cfg.get("reload", False))

    # 5) 关键点：Windows 上 `reload=True` 会启动子进程。
    #    子进程需要能 import 到本地包（例如 `server`）。
    #    所以我们把仓库根目录加到 sys.path / PYTHONPATH，并设置 uvicorn 的 app_dir。
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
    os.environ["PYTHONPATH"] = (
        repo_root_str
        if not os.environ.get("PYTHONPATH")
        else repo_root_str + os.pathsep + os.environ["PYTHONPATH"]
    )

    # 6) 启动 Web 服务
    uvicorn.run(app, host=host, port=port, reload=reload, app_dir=repo_root_str)


if __name__ == "__main__":
    main()

