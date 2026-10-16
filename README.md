# GPT 划词翻译 · GPT Selection Translator

Windows 桌面划词翻译工具。选中文字后点击 **GPT 翻译**，或按 **Ctrl+Alt+T**，在窗口中查看译文。

通过官方 **Continue with ChatGPT** 登录并授权，使用本人账号可用的 ChatGPT 套餐能力。无需填写 API Key。账号资格、可用模型、用量和功能是否开放以 OpenAI 实际返回为准。此项目不是 OpenAI 官方产品。

## 功能

- 浅粉色圆角浮动按钮，显示 ChatGPT 图标和“翻译”，尺寸随屏幕缩放适配。
- 浏览器及支持 Windows 辅助功能接口的软件中读取文字选区。
- 支持嵌套正文、网页内嵌文档的选区查找，并在网页更新后重试。
- 浏览器选区无法直接读取时，点击翻译按钮后尝试复制选区并还原剪贴板。
- 流式显示译文，支持取消和复制译文。
- 默认将非中文内容译成简体中文，主要为中文的内容译成英文。
- 每次启动及持续运行每 6 小时刷新账号可用模型；支持手动刷新。
- 可选登录 Windows 后在后台自动启动。

## 安装和启动

需要 **Windows 10/11、Python 3.12（含 Tcl/Tk 和 Python Launcher）**，以及可以连接 OpenAI 官方服务的网络。

1. 下载本仓库源码 ZIP，解压到准备长期保留的文件夹。
2. 在该文件夹打开 PowerShell，安装独立环境和依赖：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   ```

3. 双击 **启动划词翻译.vbs**。首次打开，点击 **登录 / 重新连接**，在官方网页自行完成登录和授权。固定句子验证会消耗少量账号用量。
4. 完成后返回软件，点击 **更新模型**。选中文字并按 **Ctrl+Alt+T** 或点击浮动按钮即可翻译。

也可以直接运行：

```powershell
.\.venv\Scripts\pythonw.exe .\desktop.py
```

关闭主窗口会收起到后台；**退出程序** 才会停止本次运行。再次双击启动器会显示现有窗口。

## 开机自动启动

在安装完成后运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\set-startup.ps1
```

程序会在当前用户登录 Windows 后静默启动。暂未联网会自动重试。取消自动启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\set-startup.ps1 -Disable
```

设置自启后不要单独移动启动器或重命名安装文件夹；迁移后重新运行自启设置。

## 模型更新

点击 **更新模型** 可立即读取账号目录。**自动跟随模型更新** 开启时使用官方返回列表的第一项，不根据模型名称猜测新旧。手动选择模型会关闭自动跟随并记住选择；所选模型下线后回退到列表第一项。

账号获得新模型权限后，模型会出现在列表中。此功能更新模型目录，不会自动下载新版程序；未来接口变化可能需要更新软件。

## 数据与隐私

- 登录凭据保存在本机 `data/account.dpapi`，由 Windows 为当前用户加密。
- 不保存翻译历史；原文和译文保留在程序内存及界面中。
- 只有点击翻译按钮或按快捷键才发送翻译请求。
- 不读取浏览历史或已有 ChatGPT 对话。
- `data/`、登录凭据、运行日志和本机环境均被排除在仓库之外。下载者需要使用自己的账号登录。
- 退出程序不等于撤销账号授权；账号授权管理请使用 ChatGPT 官方设置。

## 兼容性

不同软件的选区支持程度不同。无法读取时，可先手动复制原文，再点击 **翻译剪贴板**。图片和扫描 PDF 需要先识别为文字。快捷键被占用时可使用浮动按钮。

## 开发验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用模拟凭据和模拟服务，不需要真实 ChatGPT 登录，不产生真实翻译请求。Windows 专用接口使本项目不能直接在 macOS/Linux 上运行。

## 官方接入文档

- [注册与登录](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [账号与会话](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [模型目录与推理](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
