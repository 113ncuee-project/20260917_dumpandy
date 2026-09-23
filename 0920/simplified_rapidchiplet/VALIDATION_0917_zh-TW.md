# 0920 正式頻寬與 Batch-1 平均功率驗證

正式頻寬 256 bits/cycle/direction；主 PPA Power 現在是 E_total/T_Batch1，舊 fixed-utilization W 為 diagnostic。[模型公式與假設](BATCH1_POWER_zh-TW.md)。

四模型以官方 RapidChiplet、seed 20260919、Latency／Area／Power=0.6／0.2／0.2，16 W／800 mm²／500 ms 執行。Power／Area 嚴格，Latency 軟限制；budget=128、episode cap=3000。

| 模型 | Chiplets | 平均 W | 舊固定 W | Energy/Inf. J | Latency ms | Area mm² | 不同候選數 |
|---|---:|---:|---:|---:|---:|---:|---:|
| resnet50 | 9 | 3.553100 | 7.894364 | 0.731097 | 205.763053 | 712.525909 | 128 |
| resnet18 | 9 | 6.960143 | 7.894364 | 0.196705 | 28.261592 | 712.525909 | 113 |
| mobilenet_v2 | 2 | 1.042139 | 1.679739 | 0.032656 | 31.335738 | 156.119659 | 128 |
| squeezenet1_1 | 1 | 0.817500 | 0.817500 | 0.029732 | 36.369993 | 77.400000 | 89 |

四模型最佳候選均符合三項目標；小於128個候選是先達episode上限。SqueezeNet本次單顆、無跨chiplet通訊，compute active佔滿觀測窗，所以新舊W相同是合理結果。

79項測試通過；另完成真實瀏覽器 ResNet-50 全嚴格搜尋、GUI 能量分項／舊 W 顯示，以及四模型 HTTP、JSON／CSV／SVG 驗證。紀錄與 source SHA-256：[gui_256_validation.json](validation/gui_256_validation.json)。

ResNet-50 Balanced三個seed，Latency／Area／Power各一個seed，共六案Q/random各評估128個候選；本次六案最佳reward均相同，沒有證據宣稱RL優於random。記錄：[multi_seed_256.json](validation/multi_seed_256.json)。數值是解析估計，不是實測；有限預算不保證全域最佳。
