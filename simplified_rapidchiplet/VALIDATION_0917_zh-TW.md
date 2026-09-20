# 0920 正式頻寬驗證

正式預設 **256 bits/cycle/direction**，200 MHz 下每方向 **51.2 Gbit/s（6.4 GB/s）**。Power 等其他硬體設定保持不變。

## 四模型重新搜尋

透過真實 GUI HTTP API 執行，backend=official；seed 20260919，Latency／Area／Power 權重 0.6／0.2／0.2。限制 16 W／800 mm²／500 ms，Power、Area 嚴格，Latency 軟限制。每模型評估預算 128，episode 上限 3000。

| 模型 | Chiplets | Power W | Area mm² | Latency ms | 實際不同候選數 |
|---|---:|---:|---:|---:|---:|
| resnet50 | 9 | 7.894364 | 712.525909 | 205.763053 | 128 |
| resnet18 | 9 | 7.894364 | 712.525909 | 28.261592 | 113 |
| mobilenet_v2 | 2 | 1.679739 | 156.119659 | 31.335738 | 128 |
| squeezenet1_1 | 1 | 0.817500 | 77.400000 | 36.369993 | 89 |

四模型的最佳候選皆符合三項 PPA 目標；不同候選數小於 128 者是先達 episode 上限。已驗證 JSON／CSV／SVG 匯出及實際 chiplet 圖。原始摘要與設定／source SHA-256 見 [gui_256_validation.json](validation/gui_256_validation.json)。

## 回歸測試

67 項測試通過，包含嚴格／軟限制、mapping／traffic、模型校準與 HTTP 匯出。正式 RapidChiplet 的每方向 link bandwidth 實際收到 256；256→512 的敏感度測試驗證 network FPS 加倍、E2E serialization 時間減半，power 係數也獨立驗證。

數值為解析估計，不是實體加速器量測，也未包含 BookSim queueing。有限預算 RL 不保證全域最佳解。

## 多 seed 與 random 對照

正式 256 頻寬下，Balanced 使用三個 seed（20260919／20／21），Latency／Area／Power 各使用 seed 20260919，共六案。每案 Q-learning 與 random 各評估 128 個不同候選。六案皆有可行候選，Q greedy policy 可重現最佳已評估 reward；本次 Q 與 random 最佳 reward 全部相同，沒有證據宣稱 RL 較優。原始紀錄：[multi_seed_256.json](validation/multi_seed_256.json)。
