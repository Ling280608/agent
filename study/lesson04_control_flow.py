# 模拟后端鉴权逻辑
user_role = "admin"
is_authenticated = True
allowed_codes = [200, 201, 204]

# 1. 基础 if-elif-else
if not is_authenticated:
    print("401 Unauthorized")
elif user_role == "admin":
    # 缩进开始：这部分代码属于 admin 分支
    print("Welcome, Admin!")
    status_code = 200
# 2. 嵌套判断与 in 运算符
    if status_code in allowed_codes:
        print("Access Granted with valid code.")
else:
    print("403 Forbidden")


# 3. 三元运算符 (Java: condition ? a : b)
# Python 的写法更接近自然语言
message = "Success" if is_authenticated else "Fail"
print(f"Status: {message}")

# 练习：
score = 85
if score >= 90:
    print("Excellent")
elif score >= 60:
    print("Good")
else:
    print("Fail")

tasks = []
if not tasks:
    print("No tasks found")
else:
    print("Tasks pending")
    