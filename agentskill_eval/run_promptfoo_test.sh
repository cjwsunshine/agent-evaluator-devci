#!/bin/bash

# 确保脚本在出错时停止执行
set -e

echo "开始运行promptfoo评估..."

# 确保Node.js路径正确
export PATH=~/node-v20.20.0-darwin-arm64/bin:$PATH

# 创建结果目录
mkdir -p results/promptfoo

# 运行promptfoo评估
echo "执行评估测试..."
npx promptfoo eval --config promptfooconfig.js

# 检查评估结果
echo "评估完成，查看结果..."
ls -la results/promptfoo/

echo "promptfoo评估流程执行成功！"
