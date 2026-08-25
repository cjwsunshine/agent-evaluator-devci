// =============================================================================
// PikoCI pipeline: Agent 持续评测
//
// 启动服务:
//   ./pikoci server \
//     --db-system mem \
//     --jwt-secret my-secret \
//     --run-worker \
//     --pipeline-name agent-eval \
//     --pipeline-config pipeline.hcl
//
// 触发方式: Web UI (http://localhost:8080) -> agent-eval -> evaluate job -> Trigger
//           填写 input 表单后确认。
//
// 前置条件 (host):
//   - Python 3.11+ 在 PATH 中
//   - Node.js 20+ 在 PATH 中 (npx 可用)
//   - ARK_API_KEY 环境变量 (DeepEval/TruLens/Promptfoo-grader 调用方舟 LLM)
// =============================================================================

// 被测 Agent：默认走 scripts/pipeline_agent.py 适配器，它会读取网页"持续评测"
// 页选定并落盘到 instance/pipeline/agent.json 的 Agent（上传脚本 / HTTP API /
// 本地模块）。也可用 --var agent_script=my_agent.py 直接指定一个脚本文件覆盖。
variable "agent_script" {
  type    = string
  default = "scripts/pipeline_agent.py"
}

variable "min_avg_score" {
  type    = number
  default = 60
}

variable "min_pass_rate" {
  type    = number
  default = 0.7
}

// PikoCI worker 在临时目录里执行每个 task（不会自动 cd 到 pipeline.hcl 所在
// 目录），所以显式指定项目根目录，每个 task 开头 cd 进去。
// 换机器部署时改这里，或用 --vars vars.json 覆盖。
variable "project_dir" {
  type    = string
  default = "/Users/cjw/cjw/cjwproject/agent_evaluator-dev_ci"
}

// 单作业：八个顺序任务 (setup -> deepeval -> promptfoo -> trulens -> ragas -> merge -> report -> gate)
// PikoCI 的 task 通过 $PIKOCI_OUTPUT 把变量传给后续任务 (引用名 $TASK_<NAME>_<KEY>)。
job "evaluate" {
  // 可配置参数通过文件顶部的 variable 块定义（agent_script / min_avg_score /
  // min_pass_rate），在下方用 ${var.<name>} 引用。
  // 手动触发前若要改默认值，编辑本文件的 variable default，或启动服务时用
  //   --vars vars.json  （vars.json 形如 {"agent_script":"my_agent.py"}）
  // 覆盖；本地直接运行可用 ./pikoci run --var agent_script=my_agent.py ...

  // ---- 1. 安装依赖 & 创建带时间戳的输出目录 ----
  task "setup" {
    run "exec" {
      path = "/bin/sh"
      args = ["-c", <<-EOT
        set -eu
        cd "${var.project_dir}"
        echo "=== Setup: installing dependencies ==="
        python3 -m pip install -r requirements.txt --quiet
        if [ -f package.json ]; then npm install --silent; fi
        EVAL_OUTPUT_DIR="./eval_output/$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$EVAL_OUTPUT_DIR"
        echo "Output directory: $EVAL_OUTPUT_DIR"
        # 把 EVAL_OUTPUT_DIR 传给后续 task（PikoCI 会以 $TASK_SETUP_EVAL_OUTPUT_DIR 暴露）
        echo "EVAL_OUTPUT_DIR=$EVAL_OUTPUT_DIR" >> "$PIKOCI_OUTPUT"
      EOT
      ]
    }
  }

  // ---- 2. DeepEval (pytest) ----
  task "deepeval" {
    run "exec" {
      path = "/bin/sh"
      args = ["-c", <<-EOT
        set -eu
        cd "${var.project_dir}"
        echo "=== DeepEval: running pytest ==="
        EVAL_OUTPUT_DIR="$TASK_SETUP_EVAL_OUTPUT_DIR" \
        AGENT_SCRIPT="${var.agent_script}" \
        python3 -m pytest tests/ -v
        echo "=== DeepEval complete ==="
      EOT
      ]
    }
  }

  // ---- 3. Promptfoo (CLI) ----
  task "promptfoo" {
    run "exec" {
      path = "/bin/sh"
      args = ["-c", <<-EOT
        set -eu
        cd "${var.project_dir}"
        # 禁用遥测/更新检查（否则进程退出时可能因 telemetry.shutdown 超时返回 100）
        export PROMPTFOO_DISABLE_TELEMETRY=1
        export PROMPTFOO_DISABLE_UPDATE=true
        echo "=== Promptfoo: generating config ==="
        AGENT_SCRIPT="${var.agent_script}" \
          python3 scripts/gen_promptfoo_config.py
        RAW="$TASK_SETUP_EVAL_OUTPUT_DIR/promptfoo_raw.json"
        # 如果 selection.json 关闭了 promptfoo 或没选任何指标，则不跑 npx
        # （空配置会让 promptfoo 报错），转换器会写 skip-only 结果。
        PROMPTFOO_RUN_COUNT=$(AGENT_SCRIPT="${var.agent_script}" python3 -c \
          "from scripts.eval_common import *; s=load_selection(); c,_=filter_cases_for_tool(load_test_cases(),s,'promptfoo'); print(len(c))" 2>/dev/null || echo 0)
        if [ "$PROMPTFOO_RUN_COUNT" -eq 0 ]; then
          echo "=== Promptfoo: no cases selected, skipping eval ==="
        else
          echo "=== Promptfoo: running $PROMPTFOO_RUN_COUNT case(s) ==="
          set +e
          npx --yes promptfoo eval \
            --config promptfooconfig.yaml \
            --output "$RAW" \
            --no-cache
          rc=$?
          set -e
          # promptfoo 偶发在评测已成功写出结果后，因遥测关闭超时而以非零退出；
          # 只要结果文件已生成就视为成功，继续转换。
          if [ $rc -ne 0 ] && [ ! -s "$RAW" ]; then
            echo "promptfoo eval failed (exit=$rc) and no output file produced"
            exit $rc
          fi
        fi
        echo "=== Promptfoo: converting results ==="
        EVAL_OUTPUT_DIR="$TASK_SETUP_EVAL_OUTPUT_DIR" \
          python3 scripts/convert_promptfoo_results.py
        echo "=== Promptfoo complete ==="
      EOT
      ]
    }
  }

  // ---- 4. TruLens (Python script) ----
  task "trulens" {
    run "exec" {
      path = "/bin/sh"
      args = ["-c", <<-EOT
        set -eu
        cd "${var.project_dir}"
        echo "=== TruLens: running evaluation ==="
        EVAL_OUTPUT_DIR="$TASK_SETUP_EVAL_OUTPUT_DIR" \
        AGENT_SCRIPT="${var.agent_script}" \
          python3 scripts/run_trulens.py
        echo "=== TruLens complete ==="
      EOT
      ]
    }
  }

  // ---- 5. RAGAS (Python script) ----
  task "ragas" {
    run "exec" {
      path = "/bin/sh"
      args = ["-c", <<-EOT
        set -eu
        cd "${var.project_dir}"
        echo "=== RAGAS: running evaluation ==="
        EVAL_OUTPUT_DIR="$TASK_SETUP_EVAL_OUTPUT_DIR" \
        AGENT_SCRIPT="${var.agent_script}" \
          python3 scripts/run_ragas.py
        echo "=== RAGAS complete ==="
      EOT
      ]
    }
  }

  // ---- 6. 合并结果 ----
  task "merge" {
    run "exec" {
      path = "/bin/sh"
      args = ["-c", <<-EOT
        set -eu
        cd "${var.project_dir}"
        echo "=== Merging results ==="
        EVAL_OUTPUT_DIR="$TASK_SETUP_EVAL_OUTPUT_DIR" \
        AGENT_SCRIPT="${var.agent_script}" \
          python3 scripts/merge_results.py
        echo "=== Merge complete ==="
      EOT
      ]
    }
  }

  // ---- 7. 生成 HTML 报告 ----
  task "report" {
    run "exec" {
      path = "/bin/sh"
      args = ["-c", <<-EOT
        set -eu
        cd "${var.project_dir}"
        echo "=== Generating HTML report ==="
        EVAL_OUTPUT_DIR="$TASK_SETUP_EVAL_OUTPUT_DIR" \
          python3 scripts/generate_report.py
        echo "Report: $TASK_SETUP_EVAL_OUTPUT_DIR/report.html"
        echo "=== Report complete ==="
      EOT
      ]
    }
  }

  // ---- 8. 质量门禁（失败不阻塞整个作业） ----
  task "gate" {
    run "exec" {
      path = "/bin/sh"
      args = ["-c", <<-EOT
        set +e
        cd "${var.project_dir}"
        echo "=== Quality gate ==="
        EVAL_OUTPUT_DIR="$TASK_SETUP_EVAL_OUTPUT_DIR" \
        GATE_MIN_AVG_SCORE="${var.min_avg_score}" \
        GATE_MIN_PASS_RATE="${var.min_pass_rate}" \
          python3 scripts/quality_gate.py
        rc=$?
        if [ $rc -ne 0 ]; then
          echo ""
          echo "⚠️  质量门禁未通过 (exit=$rc)。报告已生成，请查看 $TASK_SETUP_EVAL_OUTPUT_DIR/report.html"
          echo "   调整阈值或修复 Agent 后重新触发。"
        fi
        # 不阻塞流水线（报告已生成）
        exit 0
      EOT
      ]
    }
  }
}
