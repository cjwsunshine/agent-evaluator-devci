def run(query, input_payload=None):
    """示例Agent函数，支持结构化调用。

    入口函数签名示例：func(query, [input_payload]) — 平台支持两种签名。

    Args:
        query: 用户问题文本
        input_payload: 结构化输入（TestCase.input_payload），可选

    Returns:
        dict 或可转字符串的任意类型：
        - dict: platform 会把整个字典存入 TaskTestCase.agent_output_payload，
                'answer' 字段用于显示和评分，'tool_calls'/'trace'/'context' 会被评分器消费
        - str 或其它类型：原样用于评分，无结构化存储
    """
    # 天气场景：模拟调用工具后再回答
    if '天气' in query or 'weather' in query.lower():
        answer = '今天天气晴朗，气温28度，相对湿度60%。'
        return {
            'answer': answer,
            'tool_calls': [
                {
                    'name': 'get_weather',
                    'arguments': {'city': '北京' if '北京' in query or 'beijing' in query.lower() else '上海'},
                    'result': {'temp': 28, 'condition': '晴', 'humidity': 60}
                }
            ],
            'trace': {
                'steps': [
                    {'step': 1, 'action': '识别意图：天气查询'},
                    {'step': 2, 'action': '调用天气API get_weather'},
                    {'step': 3, 'action': '返回自然语言回答'},
                ],
                'total_tokens': 1234,
                'latency_ms': 892
            },
            'context': '本地天气缓存：北京市朝阳区2025-06-15 16:30气象站数据'
        }

    # 数学计算场景
    if '加' in query or '+' in query or '计算' in query:
        answer = '2 + 2 = 4'
        return {
            'answer': answer,
            'tool_calls': [
                {'name': 'calculate', 'arguments': {'expression': '2 + 2'}, 'result': 4}
            ],
            'trace': {
                'steps': [
                    {'step': 1, 'action': '解析表达式为 2 + 2'},
                    {'step': 2, 'action': '调用计算器工具'},
                ],
            },
        }

    # 通用：纯文本回答
    answer = '你好！我是示例Agent，目前支持查询天气和数学计算。'
    if '时间' in query or '几点' in query:
        import datetime
        answer = f'当前时间是：{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
    elif '你好' in query or 'Hello' in query:
        answer = '你好！我是一个示例Agent。'
    else:
        answer = '抱歉，我无法回答这个问题。'

    return {'answer': answer, 'tool_calls': [], 'trace': None}


# 兼容平台默认入口函数名 run_agent
run_agent = run