class PostService:
    # 这里的 tags 相当于 Java 的 static List<String> tags
    # 它是属于“类”的，而不是属于“某个对象”的
    tags = [] 

    def __init__(self, title):
        self.title = title # 实例变量，每个对象独有一份

# 灾难现场
s1 = PostService("First Post")
s2 = PostService("Second Post")

s1.tags.append("Java") # 我以为只给 s1 加了标签
print(s2.tags)         # 结果：['Java']！s2 也被影响了，因为它们共享同一个内存地址

class Order:
    def __init__(self, order_id):
        self.order_id = order_id

o1 = Order(101)
o1.temporary_tag = "Urgent" # 合法！Java 绝对做不到
print(o1.temporary_tag)

# 为什么能做到？
# 因为 Python 对象内部维护着一个名为 __dict__ 的字典
print(o1.__dict__) # 结果：{'order_id': 101, 'temporary_tag': 'Urgent'}


# class Student(object):
#     def __init__(self, name, gender):
#         self.name = name
#         self.gender = gender


# 练习
# 请把下面的Student对象的gender字段对外隐藏起来，用get_gender()和set_gender()代替，并检查参数有效性：
# class Student(object):
#     def __init__(self, name, gender):
#         self.name = name
#         self.gender = gender

class Student(object):
    def __init__(self, name, gender):
         self.__name = name
         self.__gender = gender

    def get_gender(self):
        return self.__gender
    
    def set_gender(self, gender):
        if gender is not None and type(gender) == str:
            self.__gender = gender
        else:
            raise ValueError('Invalid gender')
            

bart = Student('Bart', 'male')
if bart.get_gender() != 'male':
    print('测试失败!')
else:
    bart.set_gender('female')
    if bart.get_gender() != 'female':
        print('测试失败!')
    else:
        print('测试成功!')