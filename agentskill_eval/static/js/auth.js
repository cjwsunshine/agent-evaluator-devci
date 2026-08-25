const API_BASE = '/api';

let currentUser = null;

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

async function apiCall(endpoint, method = 'GET', data = null) {
    const headers = {
        'Content-Type': 'application/json'
    };

    if (currentUser) {
        headers['X-User-Id'] = currentUser.id;
    }

    const options = {
        method,
        headers
    };

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
    const tabBtns = document.querySelectorAll('.tab-btn');
    const formContainers = document.querySelectorAll('.form-container');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.dataset.tab;

            tabBtns.forEach(b => b.classList.remove('active'));
            formContainers.forEach(f => f.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(`${tabName}-form`).classList.add('active');
        });
    });
});

async function login() {
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;

    if (!username || !password) {
        showToast('请填写用户名和密码', 'error');
        return;
    }

    try {
        const result = await apiCall('/auth/login', 'POST', { username, password });

        if (result.success) {
            currentUser = result.user;
            localStorage.setItem('currentUser', JSON.stringify(currentUser));
            showToast('登录成功', 'success');
            window.location.href = '/index';
        } else {
            showToast(result.message || '登录失败', 'error');
        }
    } catch (error) {
        showToast(error.message || '登录失败', 'error');
    }
}

async function register() {
    const username = document.getElementById('register-username').value.trim();
    const email = document.getElementById('register-email').value.trim();
    const password = document.getElementById('register-password').value;
    const confirmPassword = document.getElementById('register-confirm-password').value;

    if (!username || !email || !password) {
        showToast('请填写所有字段', 'error');
        return;
    }

    if (password !== confirmPassword) {
        showToast('两次密码输入不一致', 'error');
        return;
    }

    try {
        const result = await apiCall('/auth/register', 'POST', { username, email, password });

        if (result.success) {
            showToast('注册成功，请登录', 'success');
            document.querySelector('[data-tab="login"]').click();
        } else {
            showToast(result.message || '注册失败', 'error');
        }
    } catch (error) {
        showToast(error.message || '注册失败', 'error');
    }
}

function logout() {
    currentUser = null;
    localStorage.removeItem('currentUser');
    window.location.href = '/login';
}

function checkAuth() {
    const savedUser = localStorage.getItem('currentUser');
    if (savedUser) {
        currentUser = JSON.parse(savedUser);
        return true;
    }
    return false;
}