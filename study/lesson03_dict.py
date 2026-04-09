# 1. 定义字典 (类似 Java 的 Map<String, Object>)
user_info = {
    "id": 101,
    "username": "java_migrator",
    "role": "developer"
}

# 2. 读取数据
print(user_info["username"])  # 方式A：如果 key 不存在会抛出 KeyError 异常

# 方式B：类似 getOrDefault (推荐在后端处理 API 参数时使用)
email = user_info.get("email", "no-reply@example.com") 
print(f"用户邮箱: {email}")

# 3. 增加与修改 (语法一致)
user_info["role"] = "architect"  # 修改
user_info["last_login"] = "2026-04-03"  # 增加

# 4. 删除
del user_info["id"]
# 或者使用 pop 获取并删除
role = user_info.pop("role")

# 5. 遍历 (Java 需要 entrySet，Python 非常简洁)
for key, value in user_info.items():
    print(f"字段名: {key}, 字段值: {value}")


# 练习：
config = {
    "env": "dev",
    "port": 8080,
    "debug" : True
    }

print(config.get("host", "127.0.0.1"))
config["port"] = 9090

for key, value in config.items():
    print(f"字段名: {key}, 字段值: {value}")

for key in config.keys():
    print(f"字段名: {key}, 字段值: {config[key]}")