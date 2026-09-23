# Batch-1 平均功耗與能量：附件建議實作紀錄

## 採用方式

附件的十項主要要求已採用，主公式不另加 MAC ratio、model-size factor 或未校準的 e_MAC：

```
T = 現有 Batch-1 E2E latency（秒）
t_active,i = assigned_OPS_i / (peak_OPS_per_second × utilization × mapping_efficiency_i)
E_compute = Σ(peak_dynamic_W × utilization × t_active,i)
P_static = N × (chiplet_static_W + aggregate_PHY_W) + static_link_W + static_router_W
E_static = P_static × T
E_link = Σ(flow_bits × route_hops) × 0.5e-12 J/bit/hop
E_total = E_static + E_compute + E_link
P_avg,Batch1 = E_total / T
```

目前 peak_dynamic=0.85 W、utilization=0.75、usable throughput=19.2 GOPS/chiplet（再乘既有 mapping efficiency）。Active compute 為0.6375 W；不會把這一項計入 static，也不會在 idle／communication 時間收取 compute dynamic power。相同 group 的 chiplets 使用既有平均切分的 assigned OPS，並非重新套用另一套排程或效率係數。

未加入 target FPS、FPS input 或 `--target-fps`；**FPS 不參與 power、候選產生、constraint、reward 或候選排序**。原 pipeline FPS estimator 保留，沒有改為 `1/Batch1_latency`。原 `performance_per_w` 僅保留為相容診斷，混用 pipeline FPS 與 Batch-1 平均 W，不應拿來當逆能量或穩態 energy efficiency。

## 我對建議的補充與界線

1. 附件的「實際 active time」改稱「估計 active time」：沒有硬體 trace，數值由 assigned OPS 與現有 latency 模型的 throughput／mapping efficiency 推估。這是措辭與物理意義的修正，沒有改附件公式。
2. 現有 `phy_w=0.03` 暫依附件視為每顆 chiplet 的 aggregate static PHY 項，不按 port 數額外乘倍；若原始係數含動態活動，未來必須重新拆分校準。
3. Mapping efficiency 損失在此模型中仍屬有功耗的 active time；它是否等同真實 stall 活動須校準。utilization 同時進入 active 功率與 throughput，故 compute energy 的 utilization 因子會抵消；這是附件公式的結果，沒有額外補乘。
4. 拒絕 T≤0、NaN／∞、負能量以及每顆 active time 超過 T 的不一致資料，不用任意 epsilon 把它們變成可接受低功耗設計。平行 chiplet 的 active time **總和**可以大於 T，各顆自身不得超過 T。
5. Batch-1 平均 W 不是 peak/TDP。延長等待時間可能降低平均動態 W，但增加 static energy；因此同時顯示 latency 和 energy，不要求不同 DNN 的 W 必然不同，也不偷偷加入新的 energy reward。

SRAM／DRAM 逐次存取能量、DVFS、電壓／溫度／資料切換率和硬體活動量仍未校準。這次改善了 workload 對 power 的依賴方式，不代表取得了實測精度。

## 欄位與 constraint

| 輸出 | 定義 |
|---|---|
| `total_power_w`／GUI `power_w`／`power_avg_batch1_w` | 同一個 Batch-1 平均功率；供 PPA 限制、ratio 與 reward 使用 |
| `power_fixed_utilization_w` | 舊的 N×0.8175＋static link/router；只作 diagnostic |
| `energy_per_inference_j` | E_total |
| `static_energy_j` | E_static |
| `compute_dynamic_energy_j` | E_compute |
| `link_dynamic_energy_j` | E_link；與既有 `link_dynamic_energy_per_inference_j` 同義 |
| `static_power_w` | 不含 compute dynamic 的常駐 W |
| `chiplet_active_times_s` | 每顆實際配置 chiplet 的估計 active 秒數 |
| `chiplet_compute_dynamic_energies_j` | 每顆 compute dynamic J |
| `power_observation_window_s` | 與 Batch-1 latency 完全相同的 T |

既有 `total_chiplet_power_w`、`total_link_power_w` 現在是同一觀測窗下的平均分項；加上 router 分項會等於 `total_power_w`。Static link 分項另在 `link_static_power_w`；舊 chiplet 合計在 `chiplet_fixed_utilization_power_w`，避免把新舊口徑混加。

GUI 顯示主平均 W、Energy/Inf.（mJ）、三項能量、觀測窗及舊 diagnostic W；JSON 保留全部精度，CLI／GUI 的 CSV 同時輸出平均 W、舊 W、J/inference。既有嚴格／軟限制、0.6／0.2／0.2 偏好結構不變。

## 驗證

79 項測試通過；新增12項包含附件 A–E：MAC→compute energy、traffic→link energy、零 workload chiplet→零 compute energy、placement/link length→static link power、相同實體配置→相同 area。另驗證能量守恆、等待不等於 active、mapping efficiency、constraint 使用平均值，以及修改 network FPS 後搜尋結果／reward／power 不變。

原版 Rapid 對照見 [ppa_original_audit.json](validation/ppa_original_audit.json)：原版 power 仍是固定硬體 diagnostic；新增主 power 由本專案能量模型計算。原版原始碼、area、Batch-1 latency、256 bits/cycle 頻寬均未改動。

四模型已透過官方 RapidChiplet／GUI HTTP API 重新搜尋，並檢查 JSON／CSV／SVG 匯出。實際結果與 source SHA-256 見 [正式頻寬驗證](VALIDATION_0917_zh-TW.md)。另外以真實瀏覽器跑 ResNet-50，確認主 W、能量分項、舊 W 和 placement 可見。

重新驗證：

```powershell
.\.runtime\python-3.13.15-win64\python.exe -X utf8 -m unittest discover -s tests
.\.runtime\python-3.13.15-win64\python.exe -X utf8 tools/portable_smoke.py --budget 128
.\.runtime\python-3.13.15-win64\python.exe -X utf8 tools/audit_ppa.py
```
