# 1. 创建列表
# 类似 Java 的 List<Object> list = new ArrayList<>();
api_paths = ["/user/login", "/user/profile", "/order/list"]
print(f"完整路径列表: {api_paths}")

# 2. 增删改查
api_paths.append("/order/detail")         # Add: 在末尾添加元素
api_paths.insert(1, "/user/register")      # Insert: 在指定索引插入
api_paths.remove("/user/login")            # Delete: 根据值删除元素
api_paths[0] = "/user/update"             # Update: 修改指定位置的元素

# 3. 负数索引 (Python 独有魔法)
# 在 Java 中获取最后一个元素: list.get(list.size() - 1)
print(f"最后一个路由是: {api_paths[-1]}")
print(f"倒数第二个路由是: {api_paths[-2]}")

# 4. 列表切片 (Slicing) - 语法: [start:stop:step]
# 包含 start，不包含 stop (左闭右开)
sub_paths = api_paths[0:2] # 截取索引 0 和 1 的元素
print(f"前两个路由: {sub_paths}")

# 快捷切片：省略 start 代表从头开始，省略 stop 代表截取到末尾
print(f"从索引1开始到最后: {api_paths[1:]}")
print(f"最后两个元素: {api_paths[-2:]}")


# 练习：
list = ["Spring", "Vue", "Python"]
list.append("Flask")
print(list[1:-1])