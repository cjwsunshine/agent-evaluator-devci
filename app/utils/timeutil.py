"""时间序列化工具。

数据库里的时间字段以 datetime.utcnow() 写入，是"无时区(naive)的 UTC 时间"。
若直接 .isoformat()，输出的字符串不带时区标记（如 "2026-07-07T02:00:00"），
前端 new Date() 会误当作本地时间解析，导致显示比真实本地时间少 8 小时。

iso_utc() 给这些 naive 时间显式标注为 UTC（输出带 "+00:00"），
前端即可正确按本地时区换算显示。
"""
from datetime import datetime, timezone


def iso_utc(value):
    """把（存储为 UTC 的）datetime 序列化为带时区标记的 ISO 字符串。

    - None -> None
    - naive datetime（无 tzinfo）视为 UTC，补上 UTC 时区后再 isoformat
    - aware datetime 原样 isoformat
    """
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
