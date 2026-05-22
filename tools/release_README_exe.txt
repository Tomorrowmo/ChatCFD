ChatCFD 使用说明
================

【启动】
  方式一（推荐）：双击 start.bat
    会自动启动两个服务窗口，并打开浏览器 http://localhost:8001。
  方式二：双击 chatcfd.exe
    会在一个新窗口里启动后处理服务，本窗口跑 Agent，并自动开浏览器。

  首次启动需 10-20 秒（加载 VTK / MCP 工具），请耐心等。

【重要：不要拆分文件夹】
  本程序是一整个文件夹。chatcfd.exe 必须和 _internal 文件夹放在一起，
  不能只拷 chatcfd.exe。移动时请移动整个文件夹。

【配置 API Key（如管理员已预填，跳过）】
  用记事本打开 .env，填写：
    DASHSCOPE_API_KEY=sk-你的密钥
    OPENAI_API_KEY=sk-你的密钥
  .env 必须和 chatcfd.exe 放在同一个目录。

【关闭】
  关闭弹出的服务窗口即可。

【端口】
  PostService: 8001 （Web UI + API）
  Agent:       8090 （WebSocket）
  如有冲突，编辑 .env 修改 POST_SERVICE_PORT / AGENT_PORT。

【目录】
  chatcfd.exe   主程序入口
  _internal\    运行时 + 自研 VTK + 前端（请勿删除或移动）
  .env          配置文件（必须与 chatcfd.exe 同目录）
  start.bat     一键启动入口
  README.txt    本说明

【常见问题】
  - 启动后浏览器空白：首次启动稍慢，等 10-20 秒后刷新。
  - 端口被占用：关掉其他占用 8001/8090 的程序，或改 .env。
  - 杀毒软件误报/拦截：将整个文件夹加入白名单。
  - 双击没反应：用 start.bat 启动，可看到日志窗口。
