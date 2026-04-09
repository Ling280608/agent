import time

# 这是一个简单的日志装饰器
def log_execution(func):
    # *args 和 **kwargs 保证了装饰器能通配所有参数的函数
    def wrapper(*args, **kwargs):
        print(f"--- [日志] 开始执行函数: {func.__name__} ---")
        print(f"参数: {args}, {kwargs}")
        
        # 真正执行被装饰的函数 (类似 joinPoint.proceed())
        result = func(*args, **kwargs)
        
        print(f"--- [日志] 函数执行结束 ---")
        return result
    return wrapper

# 使用装饰器：就像在 Java 中加注解一样简单
@log_execution
def save_user_data(username: str):
    print(f"正在向数据库写入用户: {username}...")
    return {"status": "success"}

# 调用函数
response = save_user_data("Gemini_User")
print(f"最终结果: {response}")  

# 练习:
print("--------------练习------------------")
def timer(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        print(f"函数 {func.__name__} 执行时间: {end_time - start_time} 秒")
        return result
    return wrapper

@timer
def long_running_task():
    time.sleep(2)
    print("任务完成")

long_running_task()