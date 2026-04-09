# 1. 基础函数（带类型提示，方便 IDE 补全）
def calculate_tax(price: float, rate: float = 0.05) -> float:
    """计算税费，rate 默认为 0.05"""
    return price * rate

# 2. 多返回值 (Java 需要封装成一个 Map 或 Object)
def get_user_status(user_id: int):
    # 模拟数据库查询
    name = "Admin"
    is_active = True
    return name, is_active  # 实际上返回的是一个 Tuple

# 调用并“解包” (Unpacking)
username, status = get_user_status(101)
print(f"用户: {username}, 状态: {status}")

# 3. 命名参数调用 (不必按顺序传参)
print(calculate_tax(rate=0.08, price=100.0))

# 练习:
def create_api_response(code:int, message:str, data=None) -> dict:
    return {
        "code": code,
        "message": message,
        "data": data if data else {}
    }

print(create_api_response(200, "Success", {"user_id": 101}))
print(create_api_response(404, "Not Found"))

# 匿名函数 lambda 改造以下函数
# def is_odd(n):
#     return n % 2 == 1

# L = list(filter(is_odd, range(1, 20)))

L = list(filter(lambda x: x % 2 == 1, range(1, 20)))

print(L)

f = lambda x: x * x
print(f(5))