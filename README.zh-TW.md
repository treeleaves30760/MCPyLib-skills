# MCPyLib Skills

[![Validate](https://github.com/treeleaves30760/MCPyLib-skills/actions/workflows/validate.yml/badge.svg)](https://github.com/treeleaves30760/MCPyLib-skills/actions/workflows/validate.yml)

一組 [Agent Skills](https://agentskills.io)，教 AI 程式助理（Claude Code、Claude.ai、
Codex、Cursor 等）用 Python 和 [MCPyLib](https://github.com/treeleaves30760/MCPyLib)
控制 Minecraft 伺服器。

[English](README.md)

MCPyLib 由 Python 函式庫（`pip install mcpylib` 或 `uv add mcpylib`）和 Spigot/Paper
插件組成。插件會開一個 TCP 連接埠（預設 65535），在伺服器上執行帶 token 驗證的 JSON
指令。這些 skill 提供逐一對照原始碼確認過的 API、安全的操作習慣，以及經過測試的腳本，
讓助理寫出第一次就能跑、又不會毀掉世界的程式。

## 內容

| Skill | 用途 |
|---|---|
| [`mcpylib`](skills/mcpylib/SKILL.md) | 核心：檢查環境、連線、座標與建築高度、方塊 ID、block_state 與 NBT、如何在 `setblock`、`fill`、`edit`、`clone`、`getblocks` 之間選擇、效能、錯誤處理與安全規則。附完整的 72 個方法 API 參考、給其他語言用的原始 JSON 協定，以及疑難排解。 |
| [`mcpylib-building`](skills/mcpylib-building/SKILL.md) | 純 Python（不需 numpy）的程序化建築：球體、圓頂、圓柱、圓錐、金字塔、圓環、房屋、高塔、圖片轉像素畫、雜訊或高度圖地形。每個腳本都先試跑（dry run），沒有允許就拒絕覆蓋既有方塊，並寫出復原檔。 |
| [`mcpylib-minigames`](skills/mcpylib-minigames/SKILL.md) | 小遊戲與活動：有呼叫預算的輪詢迴圈、玩家加入與離開偵測、計分板、隊伍、Boss 血條、標題、音效、粒子、生物控制，以及當機也能收拾乾淨的清理機制。附「山丘之王」和怪物競技場兩個遊戲。 |
| [`mcpylib-mcp`](skills/mcpylib-mcp/SKILL.md) | 在 Claude Code、Claude Desktop、Cursor、VS Code、Codex 安裝與使用 [mcpylib-mcp](https://github.com/treeleaves30760/MCPyLib-mcp) MCP 伺服器，以及判斷什麼時候用 MCP 工具、什麼時候寫 Python 腳本比較好。 |

每個 skill 是一個資料夾：`SKILL.md`（YAML frontmatter 寫 `name` 和 `description`，
接著是說明），加上需要時才讀取或執行的 `references/` 與 `scripts/`。

## 需求

- 執行 Minecraft **26.1 以上**（以 26.3 建置）的 Paper 或 Spigot 伺服器，**Java 25**，
  `plugins/` 裡放 MCPyLib 插件 **1.2.0**。
- **Python 3.11+** 與客戶端：`pip install mcpylib` 或 `uv add mcpylib`。這些 skill 以
  1.2.0 客戶端為準；如果套件庫還只有 1.1.1 也能用，只是 `edit()` 走比較慢的路徑、
  重試行為也不同，核心 skill 有說明差異。
- 插件 token：在伺服器主控台執行 `/mcpylib token` 取得。放在環境變數或加進
  `.gitignore` 的 `.env`：
  ```
  MCPYLIB_HOST=127.0.0.1
  MCPYLIB_PORT=65535
  MCPYLIB_TOKEN=貼上-token
  ```
  mcpylib-mcp 伺服器也讀同樣的變數。

## 安裝

### Claude Code：插件市集（建議）

```text
/plugin marketplace add treeleaves30760/MCPyLib-skills
/plugin install mcpylib@mcpylib-skills
```

這會把四個 skill 裝成 `mcpylib` 插件。你的需求符合某個 skill 的描述時，Claude 會自動
載入它；也可以直接呼叫，例如 `/mcpylib:mcpylib-building`。之後用
`/plugin marketplace update mcpylib-skills` 更新。

### Claude Code：手動複製資料夾

```bash
git clone https://github.com/treeleaves30760/MCPyLib-skills
mkdir -p ~/.claude/skills
cp -r MCPyLib-skills/skills/* ~/.claude/skills/      # 個人：所有專案都能用
# 只給單一專案：cp -r MCPyLib-skills/skills/* .claude/skills/
```

Windows PowerShell：
`Copy-Item -Recurse MCPyLib-skills\skills\* "$HOME\.claude\skills\"`。重新啟動
Claude Code，再確認 skill 有列出來（問它「你有哪些 skills？」）。

### Claude.ai

1. 每個 skill 打包成一個 zip（zip 根目錄就是 skill 資料夾）：
   ```bash
   python tools/package_skills.py      # 產生 dist/mcpylib.zip、dist/mcpylib-building.zip …
   ```
2. 在 Settings > Capabilities 開啟 **Code execution and file creation**。
3. 打開 **Customize > Skills**，按 **+**，選 **Create skill** > **Upload a skill**，
   上傳 `mcpylib.zip`。其他 zip 依需要重複上傳；另外三個都建立在 `mcpylib` 之上。

Claude.ai 的沙箱通常連不到你的 Minecraft 伺服器，網路權限也依方案和設定而不同。在那裡，
這些 skill 最適合用來撰寫和檢查腳本，再由你在自己的電腦上執行。

### Codex

Codex 從 `~/.agents/skills/`（所有儲存庫）和 `.agents/skills/`（單一儲存庫）讀取 skill：

```bash
mkdir -p ~/.agents/skills
cp -r MCPyLib-skills/skills/* ~/.agents/skills/
```

啟動 Codex 後輸入 `$mcpylib`（或用 `/skills`）明確呼叫；任務符合描述時 Codex 也會自己選用。

### Cursor、Gemini CLI 等其他助理（AGENTS.md）

不支援 Agent Skills 的助理也能使用這些檔案，因為它們只是 Markdown 和 Python。把這個
儲存庫（或其中的 `skills/` 資料夾）放在專案裡或旁邊，然後在專案的 `AGENTS.md` 加上指引：

```markdown
## Minecraft 與 MCPyLib
撰寫透過 MCPyLib 控制 Minecraft 伺服器的程式之前，先讀
`MCPyLib-skills/skills/mcpylib/SKILL.md` 並依照其中的連結。蓋建築時再讀
`skills/mcpylib-building/SKILL.md`；做遊戲讀 `skills/mcpylib-minigames/SKILL.md`；
設定 MCP 讀 `skills/mcpylib-mcp/SKILL.md`。所有方法名稱與參數都必須符合
`skills/mcpylib/references/api.md`。
```

本儲存庫自己的 [AGENTS.md](AGENTS.md) 也為在這裡工作的助理做了同樣的事。

## 試試看

安裝後，可以這樣問助理：

- 「幫我檢查 MCPyLib 環境，我的玩家名稱是 Steve。」
- 「在 Steve 前面蓋一個半徑 12 的玻璃圓頂，先給我看計畫。」
- 「把 logo.png 做成 64 格寬的像素畫，放在出生點旁邊的牆上。」
- 「在 Steve 周圍開一場三波的怪物競技場，用玻璃圍牆。」
- 「幫我在 Claude Desktop 設定 mcpylib-mcp 伺服器。」

助理應該先執行 `check_setup.py`，建造前先試跑，覆蓋方塊前先問你，並保留它印出的復原指令。

## 儲存庫結構

```text
.claude-plugin/        marketplace.json + plugin.json（Claude Code 插件市集）
skills/
  mcpylib/             核心 skill：SKILL.md、references/（api、protocol、troubleshooting）、scripts/
  mcpylib-building/    建築 skill：配方與方塊參考、buildkit 與各種產生器
  mcpylib-minigames/   小遊戲 skill：迴圈、HUD 與實體參考、game_kit 與兩個遊戲
  mcpylib-mcp/         MCP 伺服器 skill：各客戶端設定與工具清單
tools/
  validate.py          檢查 frontmatter、連結、py_compile、API 簽名與 manifest
  smoke_test.py        對 tools/mock_server.py 執行每個腳本
  mock_server.py       模擬 MCPyLib 1.2.0 插件協定的離線伺服器
  package_skills.py    為 Claude.ai 產生 dist/<skill>.zip
AGENTS.md              給在本儲存庫工作的助理的說明
```

## 開發

```bash
pip install pyyaml mcpylib skills-ref
python tools/validate.py        # frontmatter、連結、py_compile、mc.* 呼叫與真實 API 比對
python tools/smoke_test.py      # 對模擬插件執行所有腳本（約 30 秒）
agentskills validate skills/mcpylib   # 官方參考驗證器，每個 skill 各跑一次
claude plugin validate .        # 有安裝 Claude Code 的話
```

`validate.py` 會確認腳本和 Markdown 裡每個 `mc.<method>(...)` 呼叫都符合已安裝
`mcpylib` 的方法簽名，也會確認 API 參考把每個公開方法以正確簽名列出剛好一次。
`.github/workflows/validate.yml` 的 GitHub Action 會在 Python 3.11 與 3.13 上執行驗證器
和冒煙測試。冒煙測試用的是插件協定的模擬伺服器，不是真正的伺服器，所以修改後也請在遊戲裡
實際測試。

## 相關專案

- [MCPyLib](https://github.com/treeleaves30760/MCPyLib)：Python 函式庫與 Spigot/Paper 插件。
- [MCPyLib-mcp](https://github.com/treeleaves30760/MCPyLib-mcp)：把 MCPyLib 包成工具的 MCP 伺服器。
- [MCPyLib 網站](https://treeleaves30760.github.io/MCPyLib-website/)：文件與展示。

## 授權

[Non-Commercial License with Commercial Exception](LICENSE)，與 MCPyLib 相同。每個
skill 資料夾都附一份 `LICENSE.txt`，單獨複製或打包時仍保有授權。
