from app.config.config import Config


# 允许在页面上编辑的非敏感字段（敏感字段见 Config.SECRET_CONFIG_KEYS，单独放行）
_EDITABLE_FIELDS = {
    # 引擎路径
    'promptfoo_path', 'promptfoo_results', 'deepeval_path', 'trulens_path',
    # Ark / 模型
    'ark_base_url', 'execution_model', 'evaluation_model',
    # RAGAS
    'ragas_base_url', 'ragas_model', 'ragas_embedding_model', 'ragas_embedding_base_url',
    'ragas_timeout_seconds',
    # 运行参数
    'max_concurrent_tasks', 'max_test_cases_per_task', 'test_case_timeout',
    'agent_api_timeout',
    # 日志
    'log_level', 'log_file',
    # PikoCI 连接
    'pikoci_url', 'pikoci_team', 'pikoci_pipeline', 'pikoci_job',
    'pikoci_user',
}


def _validate(data, current):
    """对关键字段做基本校验；返回错误信息字符串，None 表示通过。"""
    def val(key):
        # 取本次提交值；敏感字段若为空串说明"保持不变"，用当前值校验
        v = data.get(key)
        if key in Config.SECRET_CONFIG_KEYS and (v is None or (isinstance(v, str) and v.strip() == '')):
            return current.get(key)
        return v

    def http_url_error(value, label):
        if isinstance(value, str) and value.strip() \
                and not value.strip().startswith(('http://', 'https://')):
            return f'{label} 必须以 http:// 或 https:// 开头'
        return None

    err = http_url_error(val('ark_base_url'), '方舟 Base URL')
    if err:
        return err
    err = http_url_error(data.get('ragas_base_url'), 'RAGAS Base URL')
    if err:
        return err
    err = http_url_error(data.get('pikoci_url'), 'PikoCI 服务地址')
    if err:
        return err

    for key in Config.INT_CONFIG_KEYS:
        if key in data and data.get(key) not in (None, ''):
            try:
                iv = int(data.get(key))
                if iv < 1:
                    return f'{key} 必须为正整数'
            except (TypeError, ValueError):
                return f'{key} 必须为整数'

    return None


class SystemService:
    @staticmethod
    def get_config():
        try:
            # 敏感字段不回传明文
            return {'success': True, 'data': Config.get_public_runtime_config()}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @staticmethod
    def update_config(data):
        try:
            if not isinstance(data, dict):
                return {'success': False, 'message': '提交数据格式不正确'}

            current = Config.get_runtime_config()
            err = _validate(data, current)
            if err:
                return {'success': False, 'message': err}

            updates = {}
            for key in _EDITABLE_FIELDS:
                if key in data:
                    updates[key] = data.get(key)
            # 敏感字段单独放行（在 Config 层处理"空串=不变"）
            for key in Config.SECRET_CONFIG_KEYS:
                if key in data:
                    updates[key] = data.get(key)

            config = Config.update_runtime_config(updates)

            # 模型/Key 变更后，重置已懒加载的评测 judge/provider 单例，
            # 否则后续评分仍用旧配置直到重启进程。
            try:
                from app.services import deepeval_judge, trulens_provider
                deepeval_judge._judge_singleton = None
                trulens_provider._provider_singleton = None
            except Exception:
                pass

            return {
                'success': True,
                'message': '配置更新成功，新的密钥/模型设置将在下次评测时生效',
                'data': Config.get_public_runtime_config(),
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}
