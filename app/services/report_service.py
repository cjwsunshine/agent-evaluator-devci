from app.models.models import db, EvaluationTask, TaskTestCase, TestCase, EvaluationResult, EvaluationSet, Agent
from app.utils.timeutil import iso_utc
import json
import markdown
from datetime import datetime

def _percentile(sorted_values, pct):
    """线性插值百分位（pct: 0~100）。空列表返回 None。"""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return float(sorted_values[f])
    return float(sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f))


def _aggregate_efficiency(task_cases, results_by_case):
    """聚合延迟（P50/P95/P99）与工具调用步数（平均/最大）。

    延迟取 task_case.latency_ms（平台实测）；步数从各工具 detailed_log 的
    efficiency.step_count 读取（由评测引擎写入），取同一用例下的最大值去重。
    """
    latencies = sorted(tc.latency_ms for tc in task_cases if tc.latency_ms is not None)

    step_counts = []
    for tc in task_cases:
        steps_for_case = []
        for result in results_by_case.get(tc.id, []):
            if not result.detailed_log:
                continue
            try:
                detail = json.loads(result.detailed_log)
            except (ValueError, TypeError):
                continue
            eff = detail.get('efficiency') if isinstance(detail, dict) else None
            if isinstance(eff, dict) and eff.get('step_count') is not None:
                steps_for_case.append(eff['step_count'])
        if steps_for_case:
            step_counts.append(max(steps_for_case))

    step_counts.sort()
    avg_steps = (sum(step_counts) / len(step_counts)) if step_counts else None

    return {
        'sample_count': len(latencies),
        'latency_ms_p50': round(_percentile(latencies, 50), 2) if latencies else None,
        'latency_ms_p95': round(_percentile(latencies, 95), 2) if latencies else None,
        'latency_ms_p99': round(_percentile(latencies, 99), 2) if latencies else None,
        'latency_ms_min': round(min(latencies), 2) if latencies else None,
        'latency_ms_max': round(max(latencies), 2) if latencies else None,
        'step_count_avg': round(avg_steps, 2) if avg_steps is not None else None,
        'step_count_max': max(step_counts) if step_counts else None,
        'step_sample_count': len(step_counts),
    }


class ReportService:
    @staticmethod
    def _get_report_rows(user_id):
        rows = (
            db.session.query(EvaluationTask, TaskTestCase, TestCase, EvaluationResult, EvaluationSet, Agent)
            .join(TaskTestCase, TaskTestCase.task_id == EvaluationTask.id)
            .join(TestCase, TestCase.id == TaskTestCase.test_case_id)
            .join(EvaluationResult, EvaluationResult.task_case_id == TaskTestCase.id)
            .outerjoin(EvaluationSet, EvaluationSet.id == TestCase.set_id)
            .outerjoin(Agent, Agent.id == EvaluationTask.agent_id)
            .filter(EvaluationTask.user_id == user_id, EvaluationTask.status == 'completed')
            .all()
        )
        return rows

    @staticmethod
    def _build_report_groups(user_id):
        groups = {}
        for task, task_case, test_case, result, evaluation_set, agent in ReportService._get_report_rows(user_id):
            set_id = evaluation_set.id if evaluation_set else None
            agent_id = agent.id if agent else task.agent_id
            tool_name = result.tool_name
            key = (set_id, agent_id, tool_name)
            task_time = task.end_time or task.created_at or datetime.min
            existing = groups.get(key)
            if existing and (existing['sort_time'], existing['latest_task_id']) >= (task_time, task.id):
                continue

            task_results = (
                db.session.query(EvaluationResult)
                .join(TaskTestCase, TaskTestCase.id == EvaluationResult.task_case_id)
                .filter(TaskTestCase.task_id == task.id, EvaluationResult.tool_name == tool_name)
                .all()
            )
            passed_results = sum(1 for r in task_results if r.status == 'passed')
            pass_rate = (passed_results / len(task_results) * 100) if task_results else 0

            groups[key] = {
                'set_id': set_id,
                'set_name': evaluation_set.name if evaluation_set else '未归属评测集',
                'agent_id': agent_id,
                'agent_name': agent.name if agent else None,
                'tool_name': tool_name,
                'latest_task_id': task.id,
                'latest_end_time': iso_utc(task_time) if task_time else None,
                'pass_rate': pass_rate,
                'total_cases': task.total_cases,
                'sort_time': task_time
            }

        return groups

    @staticmethod
    def list_reports(user_id, evaluation_set_id=None, agent_id=None, tool_name=None):
        try:
            groups = ReportService._build_report_groups(user_id).values()
            reports = []
            for report in groups:
                if evaluation_set_id == '__none' and report['set_id'] is not None:
                    continue
                if evaluation_set_id is not None and evaluation_set_id != '__none' and report['set_id'] != evaluation_set_id:
                    continue
                if agent_id is not None and report['agent_id'] != agent_id:
                    continue
                if tool_name and report['tool_name'] != tool_name:
                    continue
                item = dict(report)
                item.pop('sort_time', None)
                reports.append(item)

            reports.sort(key=lambda item: (item['latest_end_time'] or '', item['latest_task_id']), reverse=True)
            return {'success': True, 'data': reports}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @staticmethod
    def get_overall_summary(user_id):
        try:
            rows = ReportService._get_report_rows(user_id)
            if not rows:
                return {
                    'success': True,
                    'data': {
                        'completed_tasks': 0,
                        'total_cases': 0,
                        'passed_cases': 0,
                        'pass_rate': 0
                    }
                }

            task_ids = {task.id for task, *_ in rows}
            result_ids = {result.id for *_, result, __, ___ in rows}
            passed_cases = sum(1 for *_, result, __, ___ in rows if result.status == 'passed')
            total_cases = len(result_ids)
            pass_rate = (passed_cases / total_cases * 100) if total_cases else 0

            return {
                'success': True,
                'data': {
                    'completed_tasks': len(task_ids),
                    'total_cases': total_cases,
                    'passed_cases': passed_cases,
                    'pass_rate': pass_rate
                }
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @staticmethod
    def get_report_filters(user_id):
        try:
            groups = ReportService._build_report_groups(user_id).values()
            evaluation_sets = {}
            agents = {}
            tools = set()
            for report in groups:
                evaluation_sets[report['set_id']] = report['set_name']
                if report['agent_id'] is not None:
                    agents[report['agent_id']] = report['agent_name'] or f"Agent {report['agent_id']}"
                if report['tool_name']:
                    tools.add(report['tool_name'])

            return {
                'success': True,
                'data': {
                    'evaluation_sets': [
                        {'id': set_id, 'name': name}
                        for set_id, name in sorted(evaluation_sets.items(), key=lambda item: item[1])
                    ],
                    'agents': [
                        {'id': item_id, 'name': name}
                        for item_id, name in sorted(agents.items(), key=lambda item: item[1])
                    ],
                    'tools': sorted(tools)
                }
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @staticmethod
    def generate_report(user_id, task_id):
        try:
            task = db.session.query(EvaluationTask).filter_by(id=task_id, user_id=user_id).first()
            if not task:
                return {'success': False, 'message': '任务不存在'}
            
            task_cases = db.session.query(TaskTestCase).filter_by(task_id=task_id).all()
            
            # 计算核心指标
            total_cases = len(task_cases)
            passed_cases = sum(1 for tc in task_cases if tc.status == 'passed')
            failed_cases = total_cases - passed_cases
            pass_rate = (passed_cases / total_cases * 100) if total_cases > 0 else 0
            
            # 工具评测结果
            tool_results = {}
            tools = task.tools.split(',') if task.tools else [task.evaluation_tool]
            task_case_ids = [task_case.id for task_case in task_cases]
            for tool in tools:
                results = db.session.query(EvaluationResult).filter(
                    EvaluationResult.task_case_id.in_(task_case_ids),
                    EvaluationResult.tool_name == tool
                ).all() if task_case_ids else []
                if results:
                    tool_pass_rate = sum(1 for r in results if r.status == 'passed') / len(results) * 100
                    tool_results[tool] = {'pass_rate': tool_pass_rate}
            
            # 用例明细
            case_details = []
            results_by_case = {}
            for task_case in task_cases:
                test_case = db.session.get(TestCase, task_case.test_case_id)
                case_result = {
                    'id': test_case.id,
                    'name': test_case.name,
                    'query': test_case.query,
                    'expected': test_case.expected,
                    'agent_output': task_case.agent_output,
                    'status': task_case.status,
                    'latency_ms': task_case.latency_ms,
                    'results': {}
                }

                # 各工具评测结果
                results = db.session.query(EvaluationResult).filter_by(task_case_id=task_case.id).all()
                results_by_case[task_case.id] = results
                # 该用例的步数（取各工具 detailed_log 中的最大值）
                step_count = None
                for result in results:
                    case_result['results'][result.tool_name] = {
                        'score': result.score,
                        'status': result.status,
                        'error_message': result.error_message,
                        'detailed_log': result.detailed_log
                    }
                    if result.detailed_log:
                        try:
                            detail = json.loads(result.detailed_log)
                            sc = (detail.get('efficiency') or {}).get('step_count')
                            if sc is not None:
                                step_count = max(step_count or 0, sc)
                        except (ValueError, TypeError):
                            pass
                case_result['step_count'] = step_count

                case_details.append(case_result)

            efficiency = _aggregate_efficiency(task_cases, results_by_case)

            report = {
                'task_info': {
                    'name': task.name,
                    'status': task.status,
                    'start_time': iso_utc(task.start_time),
                    'end_time': iso_utc(task.end_time),
                    'tools': tools
                },
                'summary': {
                    'total_cases': total_cases,
                    'passed_cases': passed_cases,
                    'failed_cases': failed_cases,
                    'pass_rate': pass_rate,
                    'tool_results': tool_results,
                    'efficiency': efficiency
                },
                'details': case_details
            }
            
            return {'success': True, 'data': report}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def export_report(user_id, task_id, data):
        try:
            report = ReportService.generate_report(user_id, task_id)
            if not report['success']:
                return report
            
            export_format = data.get('format', 'markdown')
            
            if export_format == 'markdown':
                return ReportService._export_markdown(report['data'])
            elif export_format == 'json':
                return {'success': True, 'data': report['data'], 'format': 'json'}
            else:
                return {'success': False, 'message': '不支持的导出格式'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def _export_markdown(report_data):
        md_content = f"""# Agent评测报告

## 任务信息
- 任务名称: {report_data['task_info']['name']}
- 状态: {report_data['task_info']['status']}
- 开始时间: {report_data['task_info']['start_time']}
- 结束时间: {report_data['task_info']['end_time']}
- 使用工具: {', '.join(report_data['task_info']['tools'])}

## 评测概览
- 总用例数: {report_data['summary']['total_cases']}
- 通过用例数: {report_data['summary']['passed_cases']}
- 失败用例数: {report_data['summary']['failed_cases']}
- 通过率: {report_data['summary']['pass_rate']:.2f}%

## 工具评测结果
"""
        
        for tool, result in report_data['summary']['tool_results'].items():
            md_content += f"- {tool}: {result['pass_rate']:.2f}%\n"
        
        md_content += "\n## 用例明细\n"
        
        for i, case in enumerate(report_data['details'], 1):
            md_content += f"### 用例 {i}\n"
            md_content += f"- 查询: {case['query']}\n"
            md_content += f"- 预期: {case['expected']}\n"
            md_content += f"- Agent输出: {case['agent_output']}\n"
            md_content += f"- 状态: {case['status']}\n"
            
            if case['results']:
                md_content += "- 评测结果:\n"
                for tool, result in case['results'].items():
                    md_content += f"  - {tool}: {result['status']} (得分: {result['score']})\n"
            
            md_content += "\n"
        
        return {'success': True, 'data': md_content, 'format': 'markdown'}
