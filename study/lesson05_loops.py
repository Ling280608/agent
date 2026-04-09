# 1. 基础范围循环 (类似 for i=0; i<5; i++)
print("--- Range Loop ---")
for i in range(5):
    print(f"当前索引: {i}")

# 2. 遍历列表并获取索引 (后端处理列表展示常用)
endpoints = ["/auth/login", "/api/v1/user", "/api/v1/order"]
for index, path in enumerate(endpoints):
    print(f"接口 #{index}: {path}")

# 3. 列表推导式 (Python 的绝招)
# 任务：从 endpoints 中筛选出包含 "api" 的路径，并转为大写
# Java 做法: list.stream().filter(s -> s.contains("api")).map(String::toUpperCase).collect(...)
api_only = [path.upper() for path in endpoints if "api" in path]
print(f"过滤后的接口: {api_only}")

# 4. While 循环 (与 Java 基本一致)
count = 3
while count > 0:
    print(f"倒计时: {count}")
    count -= 1

# 练习:
raw_data = [10, 55, 12, 80, 33, 90, 7]
processed_data = [x * 2 for x in raw_data if x > 50]
print(f"处理后的数据: {processed_data}")
for index , x in enumerate(processed_data):
    print(f"位置: {index}, 值: {x}")