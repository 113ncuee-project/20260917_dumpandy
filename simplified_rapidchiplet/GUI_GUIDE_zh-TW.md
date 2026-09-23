# Chiplet Lab：0917 GUI 與多模型版本

本版增加本機 GUI、逐項 PPA 嚴格選項、0.6／0.2／0.2 偏好，以及三個經實際 forward 校驗的新模型。沿用 0815 的硬體與 power 設定；FPS 仍然只有輸出用途。

## 開啟方式

macOS 使用者請從專案根目錄雙擊 `Start Chiplet Lab.command`；需 Python 3.10 或更新版本。首次會準備經 SHA-256 驗證的官方核心，之後可離線使用。詳細步驟見 [macOS 快速開始](../QUICK_START_macOS_zh-TW.md)。

**GitHub 同學版已改為自動安裝：** Windows 10/11 x64 完整解壓縮後，雙擊根目錄 `Start Chiplet Lab.cmd`，首次連網下載固定版本 Python 與官方 RapidChiplet，之後可離線。預設網址使用自動選取的 port，以啟動視窗顯示為準。詳見 [可攜包說明](PORTABLE_PACKAGE_zh-TW.md)。以下 `python gui.py` 是已完成環境準備者的手動啟動方式。

在本資料夾雙擊 **Start GUI.cmd**，或在 VS Code 終端執行：

```powershell
python gui.py
```

也可執行 `scripts/run_gui.ps1`，它會呼叫同一個可攜啟動器。手動 `python gui.py` 預設為 `http://127.0.0.1:8765`；若 port 被占用，執行 `python gui.py --port 8766`。關閉執行它的終端或按 Ctrl+C 即停止。GUI 僅監聽本機，無需 Flask、npm 或網路服務；PyTorch 僅用於重新校驗模型。

1. 輸入 Power **W**、封裝包圍盒 Area **mm²**、Batch-1 Latency **ms** 上限。
2. 三項各自選擇是否「嚴格遵守」，可混合使用。
3. 選擇 preference 和一個或多個模型；開始探索。
4. 結果上方切換模型。圖中點選 chiplet 可看座標、SRAM、group 與工作量。Traffic 下拉選單可指定一個 tensor 事件，查看其實際路由。
5. 可匯出 JSON、CSV、SVG；本次資料保存在 `results/gui/<job-id>/`。重新整理可回到目前工作；重新啟動伺服器後，舊工作仍留在磁碟，但需透過其匯出檔查看。

## 嚴格限制與 reward

`configs/defaults.json` 的 `ppa` 保留三個數值；新增 `strict_constraints` 的 power、area、latency 布林值。預設三項皆為 true。

- **勾選**：該項超標，候選直接失去推薦資格，其他項目不能抵銷它。`best_candidate`、`best_state`、`best_reward` 只來自符合所有嚴格限制的設計。沒有找到時三者為 null、status 為 `no_admissible_design`，GUI 不顯示違規配置圖。搜尋可能先評估候選才知道其 latency；拒絕樣本僅作為負向訓練資料。
- **未勾選**：仍然使用該上限當作目標，但允許超標。GUI 會標出超出百分比與 penalty。
- SRAM、channel 可切分性、已驗證 operator mapping、有限有效數值等架構檢查始終必須通過。
- `admissible` 表示符合所有嚴格項目；`feasible` 表示連軟目標也全部達標。不要混用這兩個欄位。

設每項比值 `r = 實際值 / 上限`，權重為 `w`：

```text
cost    = Σ w × r
base    = 1 / (1 + cost)
bonus   = 0.25 × Σsoft w × max(0, 1 − r)
penalty = Σsoft w × e / (1 + e),  e = max(0, r − 1)
reward  = base + bonus − penalty
```

soft 的總和僅包含未勾選項目。0.25 的 bonus 係數與飽和 penalty 是明確的研究設計選擇，並非硬體量測常數。超標越多仍持續扣分，cost 也持續上升。相同其餘指標下，某項變差不會得到更高 reward。嚴格拒絕樣本使用 `−2 − Vhard/(1+Vhard)`；任何有效可接受樣本都比它高，Q 不會因軟 penalty 而偏好嚴格違規樣本。best archive 在可接受集合內只按 reward 排名。

| Preference | Power | Area | Latency |
|---|---:|---:|---:|
| Balanced | 1/3 | 1/3 | 1/3 |
| Power | 0.6 | 0.2 | 0.2 |
| Area | 0.2 | 0.6 | 0.2 |
| Latency | 0.2 | 0.2 | 0.6 |

設定中的 `epsilon_start=0.8` 是 RL 初始探索率，不是 PPA 偏好權重，維持原值。

CLI 使用相同實作（CLI latency 的單位仍為 ns）：

```powershell
python run.py --models resnet50 resnet18 mobilenet_v2 squeezenet1_1 --preference latency --no-strict-latency --max-latency-ns 500000000 --max-area-mm2 800 --max-power-w 16
```

`--strict-power` / `--no-strict-power`、area、latency 各自可覆寫 config。GUI 控制不會改寫 defaults.json。

## 模型與實際校驗

以下四個模型均執行 torchvision **2.6.0 PyTorch / 0.21.0 torchvision CPU** 實作，`weights=None`、eval、FP32、batch 1、3×224×224。完整網路 forward 與逐 block forward 輸出一致且為有限的 `[1,1000]`。沒有下載 pretrained weights，也未評量分類 accuracy。

| 模型 | 參數數 | FP32 權重 MiB | Conv/Linear MAC G | Blocks |
|---|---:|---:|---:|---:|
| ResNet-50 v1.5 | 25,557,032 | 97.492340 | 4.089184256 | 18 |
| ResNet-18 | 11,689,512 | 44.591949 | 1.814073344 | 10 |
| MobileNetV2 | 3,504,872 | 13.370026 | 0.300774272 | 20 |
| SqueezeNet 1.1 | 1,235,496 | 4.713043 | 0.349151936 | 10 |

MiB = 2²⁰ bytes；權重包含可訓練 parameters，未加 checkpoint 格式開銷及 BN running-stat buffers。MAC 只計 Conv2d 與 Linear，grouped/depthwise Conv 有除以 groups；BN、activation、pool、residual add 和 concat 的計算或搬移成本未獨立估計。MAC 與硬體的 `op_per_mac=2` 分開，不能拿 MAC 與 2×MAC 的 OPS 混比。

來源：[ResNet 官方程式](https://docs.pytorch.org/vision/0.21/_modules/torchvision/models/resnet.html)、[MobileNetV2 官方程式](https://docs.pytorch.org/vision/0.21/_modules/torchvision/models/mobilenetv2.html)、[SqueezeNet 官方程式](https://docs.pytorch.org/vision/0.21/_modules/torchvision/models/squeezenet.html)。完整逐 operator shape/MAC 紀錄為 `validation/model_forward_validation.json`；產生器為 `tools/calibrate_models.py`。

重新執行校驗（套件僅裝在此專案）：

```powershell
python -m pip install --target .model_runtime --no-cache-dir torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cpu
python tools/calibrate_models.py
```

`.model_runtime/` 已加入 gitignore。一般 GUI 搜尋直接讀取已校驗 metadata，不在每個候選內重跑 PyTorch。其他 EfficientNet／ShuffleNet 原型仍留於歷史 catalog，未出現在 GUI 的已校驗模型清單。

## Traffic 與圖的意義

GUI 從 `best_candidate.connection_graph` 讀取真實 `(x,y)`、chiplet 邊長與 physical links，不另外製造展示用拓撲。路由在這些 physical links 上採用和 evaluator 相同的 shortest-path／lowest-ID tie-break。JSON 包含每條 flow 的 `path`，CSV 是摘要，SVG 為目前所選事件的圖。

- **ResNet-18/50**：OC 是完整輸入複製、分片輸出；IC 是輸入分片、partial output 歸約到 leader。相鄰 Conv、projection 與 identity 的必要交換仍保留。
- **MobileNetV2**：目前開放 single/OC，IC 被 action mask 排除。PW expand 的輸出 shard 可直接由同一 chiplet 的 depthwise 使用；DW 之後的 dense PW projection 才需要 all-gather。第一個無 expansion 的 block 直接接收 channel shards，不做 dense input broadcast。DW 不產生 partial-sum reduction。
- **SqueezeNet**：每個 Fire 的 squeeze → expand 1×1 / expand 3×3 → concat 全部留在同一 chiplet，因此分支及 concat 連線為本地操作，沒有跨晶粒 traffic。可在不同 Fire block 之間切 pipeline group；尚未實作 Fire 內跨 chiplet 的 concat offset ownership，故禁止該平行 mapping，而非假設它已支援。
- 一對多為每個 consumer 所需 tensor 區間的獨立 unicast；多對一依 OC shard 或 IC leader ownership 收集，不是任意平均分流。GUI 中「整次推論」是累積流量，不能解讀成所有 flows 同時發生。

## 仍然存在的研究限制

PPA 為分析估計，並非實體加速器測量。固定 mesh、固定 row-major 放置，RL 搜尋的是 block 分組、chiplet 數量和支援的 mapping，尚未學任意 physical placement / topology。CPU forward 校驗不代表 chiplet 性能已做硬體校準。

E2E 仍為 `Σ compute + Σ serialization + Σ path`，未模擬 DRAM/cache stalls、逐 cycle queue、計算通訊 overlap。各 block SRAM 使用保守 peak activation 與 resident weights；OC/IC efficiency 仍為明確假設。Power 沿用固定 utilization 與 link length static 模型；link dynamic energy 另報 J/inference，未擅自用 FPS 換算為 power。

RL 為每個模型／偏好重新訓練的 tabular Q-learning，不宣稱跨模型泛化。128 次 unique evaluation、3000 episodes 不是完整搜尋；停止原因與實際次數都輸出。嚴格模式「本次未找到」不等於證明無解。小空間多 seed 的窮舉對照驗證 Q policy 與 best archive；實際大模型結果仍需多 seed、相同預算 baseline 和 sensitivity 分析。

正式 link bandwidth 為 **256 bits/cycle/direction**，200 MHz 下每方向 **51.2 Gbit/s（6.4 GB/s）**。舊 fixed-utilization 單 chiplet 為 **0.8175 W**，保留為 diagnostic；主功率改用 Batch-1 E/T。

## 驗證

```powershell
python -m unittest discover -s tests
```

79 項測試通過，涵蓋逐項嚴格／軟限制、所有嚴格候選被拒絕時的 JSON/CSV、reward 連續性與單調性、Q policy 小空間多 seed 對照、depthwise 通訊、Fire mapping mask、模型 shape/MAC/parameter 一致性，以及實際 HTTP 搜尋與匯出。

瀏覽器另實際驗證多模型搜尋、權重切換、取消、重新整理、chiplet 點選、事件 route overlay 與模型切換。最新正式頻寬驗證見 `VALIDATION_0917_zh-TW.md`。舊 `VALIDATION_0917_zh-TW.md`、`ASSUMPTIONS_AUDIT_20260920_zh-TW.md` 是 GUI 修改前的歷史基準；涉及模型、reward 與嚴格限制的部分以本文件為準。

## PPA 定義與原版對照

GUI Power 為 Batch-1 平均功率；Area 為配置外框。GUI 顯示 E_total、static／compute／link energy 與舊 fixed-utilization W，FPS 僅輸出。見 [能量模型說明](BATCH1_POWER_zh-TW.md)；完整公式、原版差異、忽略項與本次改動見 [PPA_AUDIT_zh-TW.md](PPA_AUDIT_zh-TW.md)。
