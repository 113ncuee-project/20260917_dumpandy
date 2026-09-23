# 0917 使用與檢查說明

**給同學的一鍵版本：** 從 GitHub 下載並解壓縮後，雙擊根目錄 `Start Chiplet Lab.cmd`，或此目錄 `Start GUI.cmd`。首次需連網，不需預裝 Python、Codex 或自行設定 RapidChiplet 路徑。詳見 [可攜包說明](PORTABLE_PACKAGE_zh-TW.md)。

本地修正基於 0917 commit `1dc98c3f607692b0da6c8fe22e3676cbbc8ab08c`。

**目前版本請先閱讀 [GUI 與多模型說明](GUI_GUIDE_zh-TW.md)。** 執行 `python gui.py` 或雙擊 `Start GUI.cmd`，可分別設定 Power／Area／Latency 的嚴格選項、選擇四個已實際校驗的模型，並查看真實放置與 traffic 路由。偏好權重已改為 0.6／0.2／0.2。下面的原始實作與驗證文件保留為修改前基準。

請閱讀 [0917_IMPLEMENTATION_REVIEW_zh-TW.md](0917_IMPLEMENTATION_REVIEW_zh-TW.md)，內含設定方法、RL reward／policy、traffic 一對多及多對一、ResNet-50 size、Rapid hardware 參數與模型限制。

實際驗證數據見 [VALIDATION_0917_zh-TW.md](VALIDATION_0917_zh-TW.md)。

```powershell
python .\run.py --preference balanced --max-latency-ns 500000000 --max-area-mm2 800 --max-power-w 16
```

設定檔為 `configs/defaults.json`。輸入只有 PPA 要求與 preference；FPS 僅在完成評估後輸出。正式預設頻寬為 **256 bits/cycle/direction**，200 MHz 下每方向為 **51.2 Gbit/s**。
