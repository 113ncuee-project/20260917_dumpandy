# Chiplet Lab：macOS 快速開始

適用於 Apple silicon（arm64）與 Intel（x86_64）Mac。

## 第一次使用

1. 從 GitHub 下載並完整解壓縮專案，或使用 `git clone`。請放在目前使用者可以寫入的資料夾。
2. 安裝 [Python 3.10 或更新版本](https://www.python.org/downloads/macos/)；不需要另外安裝套件。
3. 在專案最外層雙擊 **Start Chiplet Lab.command**。如果 macOS 阻擋第一次開啟，請在 Finder 對它按右鍵，選「打開」，再依系統提示確認。
4. 啟動器會準備經 SHA-256 驗證的官方 RapidChiplet 核心，然後以預設瀏覽器開啟 GUI。

第一次啟動需要網路連線至 `raw.githubusercontent.com`。下載由 macOS 系統 `curl` 執行，Python 啟動器仍會檢查 HTTPS 來源與 SHA-256；檔案保存在 `simplified_rapidchiplet/.runtime/`，完成後可離線啟動。分析程式只用 Python 標準函式庫，無須安裝 PyTorch、Node.js 或其他套件。

## 使用與停止

- 保留啟動時開啟的 Terminal 視窗；關閉該視窗或按 Ctrl+C 即停止 GUI。
- 搜尋結果保存在 `simplified_rapidchiplet/results/gui/`。
- 若要固定連接埠，可在 Terminal 執行 `./Start\ Chiplet\ Lab.command --port 8765`。預設會自動選擇可用的本機連接埠。
- 若官方核心已下載完成，但要確認離線啟動，可執行 `./Start\ Chiplet\ Lab.command --offline`。
- 要先準備核心而不開啟 GUI，可執行 `./Start\ Chiplet\ Lab.command --setup-only`。

如果看到「找不到 Python 3」，請安裝 Python 3.10 或更新版本，並重新開啟 Terminal 後再啟動。Windows 用的 `0920.zip` 不包含 macOS 啟動器；Mac 請下載 GitHub 專案 ZIP 或使用 Git。

GUI 功能、PPA 限制與結果解讀請見 [GUI 與多模型說明](simplified_rapidchiplet/GUI_GUIDE_zh-TW.md)。
