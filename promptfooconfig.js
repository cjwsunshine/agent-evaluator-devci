module.exports = {
  tests: [
    {
      description: '测试基本功能',
      prompt: '你好，请介绍一下你自己',
      assert: [
        {
          type: 'contains',
          value: '你好'
        }
      ]
    },
    {
      description: '测试任务执行',
      prompt: '请计算123 + 456',
      assert: [
        {
          type: 'contains',
          value: '579'
        }
      ]
    },
    {
      description: '问候测试',
      prompt: '你好',
      assert: [
        {
          type: 'contains',
          value: '你好'
        }
      ]
    },
    {
      description: '天气测试',
      prompt: '今天天气怎么样？',
      assert: [
        {
          type: 'contains',
          value: '天气'
        }
      ]
    },
    {
      description: '时间测试',
      prompt: '现在几点了？',
      assert: [
        {
          type: 'contains',
          value: '几点'
        }
      ]
    }
  ],
  providers: [
    {
      id: 'echo',
      type: 'echo'
    }
  ],
  defaultProvider: 'echo',
  outputPath: 'results/promptfoo/results.json',
  format: 'json'
};