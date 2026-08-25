const API_BASE = '/api';
let currentUser = null;
let agents = [];
let testCases = [];
let tasks = [];

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

async function apiCall(endpoint, method = 'GET', data = null) {
    const headers = { 'Content-Type': 'application/json' };
    if (currentUser) {
        headers['X-User-Id'] = currentUser.id;
    }

    const options = { method, headers };
    if (data) {
        options.body = JSON.stringify(data);
    }

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, options);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || '请求失败');
        }
        return result;
    } catch (error) {
        console.error('API调用错误:', error);
        throw error;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    currentUser = JSON.parse(localStorage.getItem('currentUser'));
    if (!currentUser) {
        window.location.href = '/login';
        return;
    }

    document.getElementById('current-user').textContent = currentUser.username || currentUser.email;

    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const pageName = item.dataset.page;
            navigateTo(pageName);
        });
    });

    loadDashboardData();
});

function navigateTo(pageName) {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
        if (item.dataset.page === pageName) {
            item.classList.add('active');
        }
    });

    document.querySelectorAll('.page').forEach(page => {
        page.classList.remove('active');
    });
    document.getElementById(`${pageName}-page`).classList.add('active');

    switch(pageName) {
        case 'home':
            loadDashboardData();
            break;
        case 'agent-config':
            loadAgents();
            break;
        case 'test-cases':
            loadTestCases();
            break;
        case 'tasks':
            loadTasks();
            break;
        case 'reports':
            loadReports();
            break;
    }
}

async function loadDashboardData() {
    try {
        const [agentsResult, testCasesResult, tasksResult] = await Promise.all([
            apiCall('/agents'),
            apiCall('/test-cases'),
            apiCall('/tasks')
        ]);

        document.getElementById('agent-count').textContent = agentsResult.data?.length || 0;
        document.getElementById('test-case-count').textContent = testCasesResult.data?.length || 0;
        document.getElementById('task-count').textContent = tasksResult.data?.length || 0;

        let totalPass = 0;
        let totalTests = 0;
        if (tasksResult.data) {
            for (const task of tasksResult.data) {
                if (task.status === 'completed' && task.results) {
                    totalTests += task.results.length;
                    totalPass += task.results.filter(r => r.pass).length;
                }
            }
        }
        const passRate = totalTests > 0 ? Math.round((totalPass / totalTests) * 100) : 0;
        document.getElementById('pass-rate').textContent = `${passRate}%`;
    } catch (error) {
        console.error('加载仪表盘数据失败:', error);
    }
}

async function loadAgents() {
    try {
        const result = await apiCall('/agents');
        agents = result.data || [];
        renderAgentTable();
    } catch (error) {
        showToast('加载Agent列表失败', 'error');
    }
}

function renderAgentTable() {
    const tbody = document.getElementById('agent-tbody');
    if (agents.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">暂无数据</td></tr>';
        return;
    }

    tbody.innerHTML = agents.map(agent => `
        <tr>
            <td>${agent.name}</td>
            <td>${agent.version || 'v1.0.0'}</td>
            <td>${agent.endpoint || '-'}</td>
            <td><span class="status-badge ${agent.status || 'active'}">${agent.status === 'active' ? '启用' : '禁用'}</span></td>
            <td class="actions">
                <button class="btn-small primary" onclick="editAgent(${agent.id})">编辑</button>
                <button class="btn-small danger" onclick="deleteAgent(${agent.id})">删除</button>
            </td>
        </tr>
    `).join('');
}

function showAgentModal(agent = null) {
    document.getElementById('agent-modal').classList.add('active');
    document.getElementById('agent-modal-title').textContent = agent ? '编辑Agent' : '添加Agent';
    document.getElementById('agent-id').value = agent?.id || '';
    document.getElementById('agent-name').value = agent?.name || '';
    document.getElementById('agent-version').value = agent?.version || '';
    document.getElementById('agent-endpoint').value = agent?.endpoint || '';
    document.getElementById('agent-api-key').value = agent?.apiKey || '';
}

function editAgent(id) {
    const agent = agents.find(a => a.id === id);
    if (agent) {
        showAgentModal(agent);
    }
}

async function saveAgent() {
    const id = document.getElementById('agent-id').value;
    const data = {
        name: document.getElementById('agent-name').value.trim(),
        version: document.getElementById('agent-version').value.trim(),
        endpoint: document.getElementById('agent-endpoint').value.trim(),
        apiKey: document.getElementById('agent-api-key').value
    };

    if (!data.name) {
        showToast('请输入Agent名称', 'error');
        return;
    }

    try {
        if (id) {
            await apiCall(`/agents/${id}`, 'PUT', data);
            showToast('更新成功', 'success');
        } else {
            await apiCall('/agents', 'POST', data);
            showToast('添加成功', 'success');
        }
        closeModal('agent-modal');
        loadAgents();
    } catch (error) {
        showToast(error.message || '保存失败', 'error');
    }
}

async function deleteAgent(id) {
    if (!confirm('确定要删除这个Agent吗？')) {
        return;
    }

    try {
        await apiCall(`/agents/${id}`, 'DELETE');
        showToast('删除成功', 'success');
        loadAgents();
    } catch (error) {
        showToast(error.message || '删除失败', 'error');
    }
}

async function loadTestCases() {
    try {
        const result = await apiCall('/test-cases');
        testCases = result.data || [];
        renderTestCaseTable();
        updateTagFilter();
    } catch (error) {
        showToast('加载测试用例失败', 'error');
    }
}

function renderTestCaseTable() {
    const tbody = document.getElementById('test-case-tbody');
    const search = document.getElementById('test-case-search').value.toLowerCase();
    const tagFilter = document.getElementById('test-case-tag-filter').value;

    let filteredCases = testCases.filter(tc => {
        const matchSearch = tc.name.toLowerCase().includes(search) ||
                          tc.query.toLowerCase().includes(search);
        const matchTag = !tagFilter || tc.tags?.includes(tagFilter);
        return matchSearch && matchTag;
    });

    if (filteredCases.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">暂无数据</td></tr>';
        return;
    }

    tbody.innerHTML = filteredCases.map(tc => `
        <tr>
            <td>${tc.name}</td>
            <td>${tc.query.substring(0, 50)}${tc.query.length > 50 ? '...' : ''}</td>
            <td>${tc.expected.substring(0, 50)}${tc.expected.length > 50 ? '...' : ''}</td>
            <td>${tc.tags || '-'}</td>
            <td class="actions">
                <button class="btn-small primary" onclick="editTestCase(${tc.id})">编辑</button>
                <button class="btn-small danger" onclick="deleteTestCase(${tc.id})">删除</button>
            </td>
        </tr>
    `).join('');
}

function updateTagFilter() {
    const select = document.getElementById('test-case-tag-filter');
    const tags = [...new Set(testCases.flatMap(tc => (tc.tags || '').split(',').filter(t => t.trim())))];
    select.innerHTML = '<option value="">全部标签</option>' +
        tags.map(tag => `<option value="${tag}">${tag}</option>`).join('');
}

function filterTestCases() {
    renderTestCaseTable();
}

function showUploadModal() {
    document.getElementById('upload-modal').classList.add('active');
}

function showTestCaseModal(testCase = null) {
    document.getElementById('test-case-modal').classList.add('active');
    document.getElementById('test-case-modal-title').textContent = testCase ? '编辑测试用例' : '添加测试用例';
    document.getElementById('test-case-id').value = testCase?.id || '';
    document.getElementById('test-case-name').value = testCase?.name || '';
    document.getElementById('test-case-query').value = testCase?.query || '';
    document.getElementById('test-case-expected').value = testCase?.expected || '';
    document.getElementById('test-case-tags').value = testCase?.tags || '';
}

function editTestCase(id) {
    const tc = testCases.find(t => t.id === id);
    if (tc) {
        showTestCaseModal(tc);
    }
}

async function saveTestCase() {
    const id = document.getElementById('test-case-id').value;
    const data = {
        name: document.getElementById('test-case-name').value.trim(),
        query: document.getElementById('test-case-query').value.trim(),
        expected: document.getElementById('test-case-expected').value.trim(),
        tags: document.getElementById('test-case-tags').value.trim()
    };

    if (!data.name || !data.query || !data.expected) {
        showToast('请填写完整信息', 'error');
        return;
    }

    try {
        if (id) {
            await apiCall(`/test-cases/${id}`, 'PUT', data);
            showToast('更新成功', 'success');
        } else {
            await apiCall('/test-cases', 'POST', data);
            showToast('添加成功', 'success');
        }
        closeModal('test-case-modal');
        loadTestCases();
    } catch (error) {
        showToast(error.message || '保存失败', 'error');
    }
}

async function deleteTestCase(id) {
    if (!confirm('确定要删除这个测试用例吗？')) {
        return;
    }

    try {
        await apiCall(`/test-cases/${id}`, 'DELETE');
        showToast('删除成功', 'success');
        loadTestCases();
    } catch (error) {
        showToast(error.message || '删除失败', 'error');
    }
}

async function uploadTestCases() {
    const fileInput = document.getElementById('test-case-file');
    const file = fileInput.files[0];

    if (!file) {
        showToast('请选择文件', 'error');
        return;
    }

    const reader = new FileReader();
    reader.onload = async (e) => {
        try {
            const content = e.target.result;
            let cases = [];

            if (file.name.endsWith('.json')) {
                cases = JSON.parse(content);
            } else if (file.name.endsWith('.csv')) {
                const lines = content.split('\n');
                const headers = lines[0].split(',').map(h => h.trim());
                for (let i = 1; i < lines.length; i++) {
                    const values = lines[i].split(',');
                    if (values.length === headers.length) {
                        const tc = {};
                        headers.forEach((h, idx) => tc[h] = values[idx]);
                        cases.push(tc);
                    }
                }
            } else {
                showToast('不支持的文件格式', 'error');
                return;
            }

            for (const tc of cases) {
                await apiCall('/test-cases', 'POST', {
                    name: tc.name,
                    query: tc.query,
                    expected: tc.expected,
                    tags: tc.tags || ''
                });
            }

            showToast(`成功上传 ${cases.length} 个测试用例`, 'success');
            closeModal('upload-modal');
            loadTestCases();
        } catch (error) {
            showToast('文件解析失败', 'error');
        }
    };
    reader.readAsText(file);
}

async function loadTasks() {
    try {
        const result = await apiCall('/tasks');
        tasks = result.data || [];
        renderTaskTable();
    } catch (error) {
        showToast('加载任务列表失败', 'error');
    }
}

function renderTaskTable() {
    const tbody = document.getElementById('task-tbody');
    const statusFilter = document.getElementById('task-status-filter').value;

    let filteredTasks = tasks.filter(t => !statusFilter || t.status === statusFilter);

    if (filteredTasks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">暂无数据</td></tr>';
        return;
    }

    tbody.innerHTML = filteredTasks.map(task => `
        <tr>
            <td>${task.name}</td>
            <td>${task.agentName || '-'}</td>
            <td>${task.tools?.join(', ') || 'promptfoo'}</td>
            <td>${task.testCaseCount || 0}</td>
            <td><span class="status-badge ${task.status}">${getStatusText(task.status)}</span></td>
            <td>${new Date(task.createdAt).toLocaleString()}</td>
            <td class="actions">
                ${task.status === 'pending' ? `<button class="btn-small success" onclick="startTask(${task.id})">启动</button>` : ''}
                ${task.status === 'running' ? `<button class="btn-small primary" onclick="viewProgress(${task.id})">查看进度</button>` : ''}
                ${task.status === 'completed' ? `<button class="btn-small primary" onclick="viewReport(${task.id})">查看报告</button>` : ''}
            </td>
        </tr>
    `).join('');
}

function getStatusText(status) {
    const statusMap = {
        'pending': '待执行',
        'running': '执行中',
        'completed': '已完成',
        'failed': '失败'
    };
    return statusMap[status] || status;
}

function filterTasks() {
    renderTaskTable();
}

async function showTaskModal() {
    document.getElementById('task-modal').classList.add('active');
    document.getElementById('task-name').value = '';

    await loadAgents();
    const agentSelect = document.getElementById('task-agent');
    agentSelect.innerHTML = '<option value="">请选择Agent</option>' +
        agents.map(a => `<option value="${a.id}">${a.name}</option>`).join('');

    await loadTestCases();
    const testCasesDiv = document.getElementById('task-test-cases');
    testCasesDiv.innerHTML = testCases.map(tc =>
        `<label><input type="checkbox" name="task-test-case" value="${tc.id}"> ${tc.name}</label>`
    ).join('');
}

async function saveTask() {
    const data = {
        name: document.getElementById('task-name').value.trim(),
        agentId: document.getElementById('task-agent').value,
        tools: Array.from(document.querySelectorAll('input[name="eval-tool"]:checked')).map(el => el.value),
        testCaseIds: Array.from(document.querySelectorAll('input[name="task-test-case"]:checked')).map(el => el.value),
        promptfooConfig: document.getElementById('task-promptfoo-config').value.trim()
    };

    if (!data.name) {
        showToast('请输入任务名称', 'error');
        return;
    }

    if (!data.agentId) {
        showToast('请选择Agent', 'error');
        return;
    }

    if (data.testCaseIds.length === 0) {
        showToast('请选择测试用例', 'error');
        return;
    }

    try {
        await apiCall('/tasks', 'POST', data);
        showToast('任务创建成功', 'success');
        closeModal('task-modal');
        loadTasks();
    } catch (error) {
        showToast(error.message || '创建任务失败', 'error');
    }
}

async function startTask(id) {
    try {
        await apiCall(`/tasks/${id}/start`, 'POST');
        showToast('任务已启动', 'success');
        loadTasks();
    } catch (error) {
        showToast(error.message || '启动任务失败', 'error');
    }
}

function viewProgress(taskId) {
    document.getElementById('progress-modal').classList.add('active');
    pollTaskProgress(taskId);
}

async function pollTaskProgress(taskId) {
    try {
        const result = await apiCall(`/tasks/${taskId}/status`);
        const task = result.data;

        document.getElementById('progress-status').textContent = getStatusText(task.status);
        document.getElementById('progress-percent').textContent = task.progress || '0%';
        document.getElementById('progress-completed').textContent = `${task.completed || 0}/${task.total || 0}`;
        document.getElementById('progress-fill').style.width = task.progress || '0%';

        if (task.details) {
            document.getElementById('progress-details').innerHTML = task.details.map(d => `
                <div class="progress-item">
                    <div class="test-name">${d.name}</div>
                    <div class="test-status ${d.status}">${d.status === 'pass' ? '✓ 通过' : '✗ 失败'}</div>
                </div>
            `).join('');
        }

        if (task.status === 'running') {
            setTimeout(() => pollTaskProgress(taskId), 2000);
        }
    } catch (error) {
        console.error('获取进度失败:', error);
    }
}

function viewReport(taskId) {
    navigateTo('reports');
    loadReportData(taskId);
}

async function loadReports() {
    await loadTasks();
    const completedTasks = tasks.filter(t => t.status === 'completed');
    if (completedTasks.length > 0) {
        loadReportData(completedTasks[0].id);
    }
}

async function loadReportData(taskId) {
    try {
        const result = await apiCall(`/reports/${taskId}`);
        const report = result.data;

        document.getElementById('report-pass-rate').style.width = report.passRate + '%';
        document.getElementById('report-pass-rate-text').textContent = report.passRate + '%';
        document.getElementById('report-total-score').textContent = report.totalScore || 0;
        document.getElementById('report-total-cases').textContent = report.totalCases || 0;

        const tbody = document.getElementById('report-tbody');
        tbody.innerHTML = (report.results || []).map(r => `
            <tr>
                <td>${r.name}</td>
                <td>${r.input?.substring(0, 50)}...</td>
                <td>${r.output?.substring(0, 50)}...</td>
                <td>${r.expected?.substring(0, 50)}...</td>
                <td><span class="status-badge ${r.pass ? 'completed' : 'failed'}">${r.pass ? '通过' : '失败'}</span></td>
                <td><button class="btn-small primary" onclick="viewResultDetail('${r.id}')">查看</button></td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('加载报告失败:', error);
    }
}

function viewResultDetail(resultId) {
    showToast('查看详情功能开发中', 'info');
}

async function exportReport(format) {
    showToast(`导出${format.toUpperCase()}功能开发中`, 'info');
}

function saveSettings() {
    const promptfooPath = document.getElementById('promptfoo-path').value;
    const promptfooResults = document.getElementById('promptfoo-results').value;

    localStorage.setItem('promptfooSettings', JSON.stringify({
        path: promptfooPath,
        results: promptfooResults
    }));

    showToast('设置已保存', 'success');
}

function closeModal(modalId) {
    document.getElementById(modalId).classList.remove('active');
}

function logout() {
    localStorage.removeItem('currentUser');
    window.location.href = '/login';
}