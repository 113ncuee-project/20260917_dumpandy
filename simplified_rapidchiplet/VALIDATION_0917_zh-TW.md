# 0917 驗證結果（2026-09-19）

基底 commit：`1dc98c3f607692b0da6c8fe22e3676cbbc8ab08c`。本文件描述本地修正版，不是原始 0917 提交已具備的結果。

## 回歸與整合測試

`python -m unittest discover -s tests`：**50 / 50 通過**，包含正式 Rapid 引擎測試，沒有 skipped tests。測試中會刻意用不存在的 engine path 驗證 fallback 警告，該警告不是正式引擎驗證失敗。

涵蓋：

- OC/IC 快取分離、mapping metadata 保留、單顆策略正規化。
- 完整枚舉兩個 block、最多三顆 chiplet 的 10 個合法設計；五個 seed 均評估完整空間，Q-policy reward 與獨立枚舉最佳值相同。
- Q 值實際驅動 exploitation；有限 episode 結束、unique evaluation 預算與無合法完整配置的處理。
- FPS 不影響 reward/PPA score，移除舊目標設定；不合法架構、NaN 指標不能當成低成本優解。
- 一對多、一對一、多對一、多對多、同組跨 block、分支 fanout/join、IC Conv 中間 reduction 與 residual shortcut；leader 已有完整輸入時不重複 gather。
- ownership 缺片／重疊拒絕、不同消費 tensor 不混在一起、每條 route 只使用實體連線。
- Rapid traffic 與逐事件 E2E bits 相同；join 等所有前驅資料，critical path 以資料抵達及資源等待為依據。
- ResNet-50 參數／MAC／activation 大小、Stem pooling 前 buffer、channel divisibility、spatial 停用及 SRAM 檢查。
- 正式 Rapid 與 local 的 area、ICI latency、power、network FPS 一致；頻寬 0.3 改 0.6 時，每方向 bandwidth 同步改動且 network FPS 加倍；兩顆 chiplet 的 static power 各增加 0.1 W 時，總 power 增加 0.2 W。
- CSV／HTML 相容輸出移除 FPS target／bonus 欄位。

## ResNet-50 正式引擎搜尋

平台：8×8 PE、200 MHz、SRAM 16 MiB、最多 16 chiplets、固定 utilization 0.75。PPA 上限：latency 0.5 秒、area 800 mm²、power 16 W。全部使用 `backend=official`。

每個案例：Q-learning 和 random search **各評估 128 個不同候選**，共享同一個最少 chiplet 起始候選。比較的是昂貴評估次數，不是相同 episode 數或 CPU 時間。reward 越大越好。

| 頻寬 bits/cycle | 偏好 | Seed | Q reward | Random reward | Q latency 秒 | Q area mm² | Q PPA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.3 | balanced | 20260919 | -1.688582 | -1.731251 | 1.605559 | 712.526 | 未通過 |
| 0.3 | balanced | 20260920 | -1.814082 | -1.788627 | 2.594749 | 951.369 | 未通過 |
| 0.3 | balanced | 20260921 | -1.769592 | -1.769210 | 2.075458 | 951.369 | 未通過 |
| 256 | balanced | 20260919 | 0.625576 | 0.625576 | 0.205763 | 712.526 | 通過 |
| 256 | latency | 20260919 | 0.681372 | 0.681372 | 0.205763 | 712.526 | 通過 |
| 256 | area | 20260919 | 0.554626 | 0.554626 | 0.205763 | 712.526 | 通過 |
| 256 | power | 20260919 | 0.655765 | 0.655765 | 0.205763 | 712.526 | 通過 |

在 0.3 頻寬的三個 seed 中，Q 比 random 好一次、差兩次。這不足以證明統計優越性，也不能保證 RL 永遠較好。七個案例的 greedy Q-policy 都能重現最佳已評估 reward，observed-transition replay 皆收斂；每個案例都有實際使用 Q 值的 exploitation steps。所有最佳候選都通過架構／SRAM 檢查。

目前 action mask 定義的 ResNet-50 設計空間有 **20,176,298** 個候選，因此七次執行的 `global_optimum_certified` 都是 false。搜尋停止原因均為 evaluation budget。

## 預設結果與解讀

預設 balanced、seed 20260919、**0.3 bits/cycle**：

- 9 chiplets；712.525909 mm²；7.894364 W。
- Batch=1 解析 latency **1.605559 秒**；FPS 估計 **1.428569**，只作輸出。
- 相較起始候選的 2.902068 秒有所改善，但仍超過 0.5 秒上限，因此 `feasible=false`，違反項目為 latency。
- 分組為 blocks `[0:8]` 1×single、`[8:11]` 2×OC、`[11:14]` 1×single、`[14:17]` 4×OC、`[17:18]` 1×single。索引為 Python 半開區間，chiplet 依各組順序連續分配。

另行測試的 **256 bits/cycle** 基準：四種偏好本次都選到相同的 9-chiplet 起始候選，latency 0.205763 秒、area 712.525909 mm²、power 7.894364 W、FPS 8.192308，全部符合 PPA。這是參數敏感度證據，不能把此數字當成預設 0.3 頻寬的結果；也不能因偏好不同就要求最佳配置一定不同。本次 baseline 案例沒有展示 RL 優於起始候選。

兩組比較下，**未找到**符合預設 0.3 頻寬 PPA 上限的候選；有限搜尋不能證明完全不存在可行解。沒有調寬使用者限制，也沒有更改預設頻寬來製造達標結果。

## 可追溯檔案

- [實作及 traffic 圖解](0917_IMPLEMENTATION_REVIEW_zh-TW.md)
- [七次比較的原始 JSON](validation/multi_seed_comparison.json)
- [預設執行的設定與 source SHA-256](validation/default_run_manifest.json)
- 完整候選／events／Q-table：`results/validation_0917/balanced/preference_search_results.json`（本地輸出，未納入 Git）。
- 重現命令：`python tools/validate_0917.py`；預設完整輸出：`python run.py --out results/validation_0917/balanced`。

所有數字來自解析模型；沒有執行實體 DNN 加速器、BookSim queueing 或模型 accuracy benchmark。模型範圍與限制見實作說明。
