def run(query):
    """
    示例Agent函数
    输入: query (字符串)
    输出: 字典，包含answer字段
    """
    # 简单的规则匹配
    if '你好' in query or 'Hello' in query:
        return {'answer': '你好！我是一个示例Agent。'}
    elif '天气' in query:
        return {'answer': '今天天气晴朗，温度适宜。'}
    elif '时间' in query:
        import datetime
        current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return {'answer': f'当前时间是：{current_time}'}
    else:
        return {'answer': '抱歉，我无法回答这个问题。'}