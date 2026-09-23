# 0920：給同學的啟動說明

適用 **Windows 10／11，Intel／AMD 64 位元電腦**。

1. 下載 repository 根目錄的 **0920.zip** 並完整解壓縮。也可選 **Code → Download ZIP** 或用 `git clone` 取得原始碼。
2. 在最外層雙擊 **Start Chiplet Lab.cmd**。
3. 第一次保持網路連線，程式會下載約 12 MB 的官方 Python 與 RapidChiplet 核心，完成後自動開啟瀏覽器。
4. 在 GUI 選模型、PPA 限制與偏好，按「開始探索」。

不必先安裝 Python、Git、Node.js、PyTorch 或 Visual Studio，也不用修改任何使用者路徑。不要直接在 ZIP 預覽視窗裡執行；請先解壓縮到有寫入權限的資料夾。預設自動使用可用的 localhost port，網址會顯示在啟動視窗。

第二次以後可離線使用。請保留啟動視窗；關閉視窗或 Ctrl+C 會停止 GUI。結果位於 `simplified_rapidchiplet/results/gui/`。

如果下載失敗，確認能連到 `www.python.org` 與 `raw.githubusercontent.com`，再雙擊同一檔案重試；已正確下載的檔案不會重抓。套件只寫入專案中的 `.runtime`，不變更系統 Python 或永久環境變數。

此版本使用官方 RapidChiplet 分析核心，沒有把它換成本地簡化 proxy。預設硬體保留 200 MHz、16 MiB SRAM 與 256 bits/cycle/direction；主功率為 Batch-1 能量／時間，舊 0.8175 W/chiplet 固定模型另列 diagnostic。四個模型的 metadata 已完成 CPU forward 校驗，因此執行設計搜尋不必下載 PyTorch。

細節：[GUI 與模型說明](simplified_rapidchiplet/GUI_GUIDE_zh-TW.md) · [可攜包與驗證](simplified_rapidchiplet/PORTABLE_PACKAGE_zh-TW.md)。
