# 0920 — Chiplet Lab

Windows 一鍵啟動包：[下載 0920.zip](0920.zip?raw=true) · [使用說明](QUICK_START_zh-TW.md)。解壓縮後雙擊 `Start Chiplet Lab.cmd`；首次需連網，不必預裝 Python。

# RapidChiplet 0917 修正版

**同學下載後直接雙擊根目錄 `Start Chiplet Lab.cmd`。** Windows 10/11 x64 首次連網即自動準備 Python 與官方 RapidChiplet，不需預裝軟體或修改路徑。請先完整解壓縮。[三步啟動說明](QUICK_START_zh-TW.md) · [可攜包與驗證](simplified_rapidchiplet/PORTABLE_PACKAGE_zh-TW.md)

主要可執行專案在 `simplified_rapidchiplet/`，基於 0917 commit `1dc98c3f607692b0da6c8fe22e3676cbbc8ab08c`。

新增 GUI：在該資料夾雙擊 **Start GUI.cmd** 或執行 `python gui.py`。支援四個實際校驗模型、逐項嚴格 PPA 限制，以及真實 chiplet 放置與路由。詳見 [GUI 使用說明](simplified_rapidchiplet/GUI_GUIDE_zh-TW.md)。

```powershell
cd .\simplified_rapidchiplet
python .\run.py --preference balanced --max-latency-ns 500000000 --max-area-mm2 800 --max-power-w 16
```

本版只要求使用者輸入 PPA 與 preference；FPS 僅為輸出指標。預設模型為已重算逐 block 大小的 ResNet-50 v1.5 FP32。硬體沿用附檔的 0815 power 與有效 0.3 bits/cycle 頻寬設定。

- [完整使用與實作檢查](simplified_rapidchiplet/0917_IMPLEMENTATION_REVIEW_zh-TW.md)
- [回歸測試與多 seed 驗證](simplified_rapidchiplet/VALIDATION_0917_zh-TW.md)
- [設定檔](simplified_rapidchiplet/configs/defaults.json)

`presentation_work/`、歷史報告及舊簡報產生工具是既有實驗資料，沒有重新計算，不代表本次修改後的結果。
