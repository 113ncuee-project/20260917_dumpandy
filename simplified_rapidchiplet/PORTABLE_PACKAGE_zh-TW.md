# 可攜式一鍵啟動包

Windows 10/11 x64：雙擊 repository 根目錄的 `Start Chiplet Lab.cmd`，或本資料夾的 `Start GUI.cmd`。首次需連網，之後可離線；不需要預裝 Python 或系統管理員權限。macOS／Linux 不包含在此 Windows 啟動包的支援範圍。

macOS 有獨立啟動方式：請使用 repository 根目錄的 `Start Chiplet Lab.command`，並依 [macOS 快速開始](../QUICK_START_macOS_zh-TW.md) 安裝 Python 3.10 或更新版本。macOS 啟動器不使用本文件描述的 Windows Python runtime。

## 安裝內容

- 官方 Python **3.13.15 Windows x64 embeddable**，由 python.org 直接取得。
- 官方 RapidChiplet commit **17176f92c91eda629a25bc11bf7959d6b963a23b** 的四個原始核心檔案，直接從上游 GitHub 下載。此版本的四檔與原先測試用的 RapidChiplet 檔案內容相同（忽略 CRLF/LF）。
- 版本、來源 URL、下載與解壓後的 SHA-256 均記錄於 `packaging/runtime-lock.json`。下載不符雜湊即停止，不會執行該檔案。
- 整個 GUI／分析核心執行路徑只使用 Python 標準函式庫；不需要安裝 upstream 繪圖腳本的 matplotlib/networkx/numpy，也不呼叫 BookSim 二進位檔。這不代表完整 RapidChiplet 的所有附加工具都沒有相依套件。

Python 的 `._pth` 把搜尋路徑隔離在專案內，不會引用電腦既有 Python、Codex 環境或 PYTHONPATH。啟動器不設定永久 PATH 或系統 ExecutionPolicy；只在本次 PowerShell 程序執行本地啟動腳本。

下載位置為 `.runtime/`，已加入 gitignore。RapidChiplet root 改成 `../.runtime/rapidchiplet`，由 config 所在目錄解析，不依賴終端目前目錄。預設 backend 改為 `official`，官方核心失敗時會明確報錯，不能默默改用 proxy。

來源：[Python 官方 Windows 發行頁](https://www.python.org/downloads/windows/)、[Python 3.13.15 官方雜湊清單](https://www.python.org/ftp/python/3.13.15/windows-3.13.15.json)、[RapidChiplet 上游](https://github.com/spcl/rapidchiplet)。Python 原始授權隨官方執行環境保留；上游 RapidChiplet 由同學直接取得，本 ZIP 不重新散布其檔案，也未替上游宣稱授權。

## 啟動與驗證命令

從本資料夾執行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_windows.ps1 -SetupOnly
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_windows.ps1 -SelfTest
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_windows.ps1 -SelfTest -Offline
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_windows.ps1 -NoBrowser -Port 8766
```

SelfTest 會在該可攜 Python 中執行四模型的官方 RapidChiplet 搜尋，檢查 GUI HTTP API、JSON／CSV／SVG，輸出 `results/portable_smoke.json`。它使用每模型 2 個候選做啟動檢查，不把這個數量冒充 128 次研究實驗。

完整回歸測試：

```powershell
.\.runtime\python-3.13.15-win64\python.exe -X utf8 -m unittest discover -s tests
```

## GitHub 發布

應提交 root 啟動檔、QUICK_START、本專案的程式／設定／GUI／tests／scripts／tools／packaging／文件。不要提交 `.runtime`、`.model_runtime` 或個人結果。`0920.zip` 與 `0920.zip.sha256` 是本版刻意提交的輕量下載包。

repository 根目錄已提供下載包；也可將 `0920.zip` 與 `.zip.sha256` 附加在 GitHub Release；同學下載、解壓縮、雙擊根目錄啟動檔即可。只用 GitHub Code → Download ZIP 或 git clone 也同樣能啟動，不依賴 Release。

重建下載包：先完成 bootstrap，接著執行

```powershell
.\.runtime\python-3.13.15-win64\python.exe tools/build_classmate_package.py
```

ZIP 採明確白名單，只包含可執行專案與文件，不帶 `.git`、Python 套件庫、臨時資料、舊簡報或整個 Desktop。每個包內檔案的 SHA-256 在 `PACKAGE_MANIFEST.json`。

## 驗證範圍

已以專案內的 Python 3.13.15 通過 79 項回歸測試，並在全新解壓目錄完成首次下載安裝及四模型 GUI API、JSON／CSV／SVG 匯出檢查。這驗證啟動與分析流程，不代表 RL 找到全域最佳解。

GUI 使用隨附的模型校準資料；若要重新跑 PyTorch forward 校準，需另外準備一般 Python 與 PyTorch 環境，該開發流程不包含在此輕量啟動包。
