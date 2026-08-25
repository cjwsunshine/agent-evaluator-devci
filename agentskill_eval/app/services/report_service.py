from app.models.models import EvaluationTask, TaskTestCase, TestCase, EvaluationResult
import json
import markdown
from datetime import datetime

class ReportService:
    @staticmethod
    def generate_report(user_id, task_id):
        try:
            task = EvaluationTask.query.filter_by(id=task_id, user_id=user_id).first()
            if not task:
                return {'success': False, 'message': '任务不存在'}
            
            task_cases = TaskTestCase.query.filter_by(task_id=task_id).all()
            
            # 计算核心指标
            total_cases = len(task_cases)
            passed_cases = sum(1 for tc in task_cases if tc.status == 'passed')
            failed_cases = total_cases - passed_cases
            pass_rate = (passed_cases / total_cases * 100) if total_cases > 0 else 0
            
            # 工具评测结果
            tool_results = {}
            tools = task.tools.split(',')
            for tool in tools:
                results = EvaluationResult.query.filter_by(
                    task_case_id=task_cases[0].id if task_cases else 0,
                    tool_name=tool
                ).all()
                if results:
                    tool_pass_rate = sum(1 for r in results if r.status == 'passed') / len(results) * 100
                    tool_results[tool] = {'pass_rate': tool_pass_rate}
            
            # 用例明细
            case_details = []
            for task_case in task_cases:
                test_case = TestCase.query.get(task_case.test_case_id)
                case_result = {
                    'id': test_case.id,
                    'query': test_case.query,
                    'expected': test_case.expected,
                    'agent_output': task_case.agent_output,
                    'status': task_case.status,
                    'results': {}
                }
                
                # 各工具评测结果
                results = EvaluationResult.query.filter_by(task_case_id=task_case.id).all()
                for result in results:
                    case_result['results'][result.tool_name] = {
                        'score': result.score,
                        'status': result.status,
                        'error_message': result.error_message
                    }
                
                case_details.append(case_result)
            
            report = {
                'task_info': {
                    'name': task.name,
                    'status': task.status,
                    'start_time': task.start_time.isoformat() if task.start_time else None,
                    'end_time': task.end_time.isoformat() if task.end_time else None,
                    'tools': tools
                },
                'summary': {
                    'total_cases': total_cases,
                    'passed_cases': passed_cases,
                    'failed_cases': failed_cases,
                    'pass_rate': pass_rate,
                    'tool_results': tool_results
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