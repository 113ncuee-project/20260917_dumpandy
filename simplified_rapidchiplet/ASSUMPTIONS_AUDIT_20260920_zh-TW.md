# 0917 修正版：假設、嚴謹性與可調變量盤點

檢查日期：2026-09-20。範圍是目前 `audit_0917_snapshot/simplified_rapidchiplet` 的執行入口、模型、mapping、traffic、PPA、RL、設定與相關歷史工具；不是對工作區其他版本、歷史簡報或外部 Rapid 全部原始碼的逐行認證。本次只盤點，沒有改動演算法、硬體設定或重跑實驗。

目前應定位為「具備回歸測試的解析式 DSE 原型」。50 項測試通過代表已測案例的實作一致性，不代表真實晶片 PPA 準確、數值運算結果已驗證、全域最佳或 RL 已具備泛化能力。

## 一、哪些值從哪裡來？

| 類別 | 內容 | 可以怎麼表述 |
| --- | --- | --- |
| 使用者附檔／0815 平台沿用 | 8×8 PE、200 MHz、utilization 0.75、寬度 8.79772697916911 mm、間距 0.15 mm、internal/PHY latency 3/12 cycles、有效頻寬 0.3、power 相關係數 | 沿用實驗平台設定；僅因沿用，不能認定有實測依據。256 是附檔另列的頻寬基準。 |
| 0917 既有平台設定 | 每顆 SRAM 16 MiB、最多 16 chiplets | 設計空間的容量假設；不是由 ResNet 必然推導出來的數字。 |
| 修正版固定的模型定義 | ResNet-50 v1.5、batch 1、FP32、224×224、1000 classes，依形狀公式重算 metadata | 模型規格與公式推導；沒有執行 PyTorch inference、accuracy 或 accelerator benchmark。 |
| 實作採用的建模選擇 | OC/IC efficiency、平均分工、保守 SRAM buffer、通訊協定、串行 E2E、固定功耗、RL reward／超參數 | 需要明列為假設或演算法選擇，不能當作量測事實。 |
| 使用者系統需求 | 0.5 秒、800 mm²、16 W 與 preference | 原附檔中的可執行實驗上限；可由實際需求更改，不是硬體或模型自動決定。 |

## 二、模型與硬體假設

| ID | 現況／假設 | 不嚴謹或未驗證之處 | 對結果的影響／處理方向 |
| --- | --- | --- | --- |
| A1 | 同組 operations 與 weights 平均分到 N 顆 | 未描述 PE dataflow、tile、SRAM 存取頻寬、工作不均及 operator 細部映射 | MAC/N 的 speedup 可能過度樂觀；需要逐 operator 的成本模型。 |
| A2 | single efficiency=1；OC=0.95；IC=0.85；超過 2 顆每多一顆扣 0.01，最多扣 0.15 | 人工係數，未做硬體校準；compute 部分先驗偏向 OC | RL 的偏好可能來自人設係數；應校準或做移除此係數、改變係數的消融比較。 |
| A3 | 所有 block 固定 utilization=0.75，每 PE 每 cycle 2 operations | 沒有逐層利用率，也沒有驗證這個 PE 是否在 FP32 下確實提供該吞吐量 | 不能把解析 FP32 workload 與未定義數值格式的 PE 吞吐量直接稱為已驗證平台。 |
| A4 | 計算量只涵蓋 Conv／Linear MAC | BN、ReLU、pooling、residual Add、reduction 加法等未單獨計算時間 | 通訊有計入不代表相關算術成本也完整；需補 operator 成本或明列忽略範圍。 |
| A5 | 權重常駐，SRAM≈weights/N＋保守 live buffer；DAG 使用較保守的輸入輸出保留量 | 不是精確 allocation/liveness 模擬；未含所有暫存、alignment、bank/port 限制 | 可能排除可透過 streaming 執行的配置，也不能保證所有判為可行的配置都能落實。 |
| A6 | 輸入已在首組 leader，權重已載入；沒有外部記憶體控制器節點或最終輸出回傳成本 | 未計 host/DRAM→chiplet、權重搬運、chiplet→host 與 memory stalls | 目前 E2E 的範圍是這套模型內的推論，不是完整應用服務時間。 |
| A7 | compute 與通訊事件全部串行相加 | 未模擬 compute/communication overlap；一般分支 DAG 的並行性不進入主要 PPA latency | 對重疊／並行可能高估，但忽略其他成本可能低估，不能稱嚴格上界或下界。 |
| A8 | 頻寬是每方向固定 bits/cycle，所有 links 相同，與 compute 共用 frequency | 沒有封包／flit／header、buffer、backpressure、跨事件 queueing、router arbitration 模擬 | serialization 為流體式近似；不是 cycle-accurate network latency。事件內共享 link 的 bits 有相加，不能說完全沒算任何競爭。 |
| A9 | OC broadcast=多份 unicast；IC=分片、leader reduction；固定 channel 區間 | 是一套選定的合法抽象協定，不是所有硬體唯一或最省 traffic 的方式 | 沒有 tree/ring reduction、硬體 multicast、廣泛跨消費者 cache reuse；需要比較協定或明列固定。 |
| A10 | 預設固定 mesh、接近方形 row-major placement；group 使用連續 chiplet ID；最少 hop，平手最低 ID | RL 不搜尋 topology、placement、route 或 leader；未驗證 channel-dependency deadlock freedom／virtual channel 配置 | mapping 結果受指定佈局與路由侷限，不能稱完整 chiplet 系統最佳化。底層有 tree helper 不等於目前 RL 搜尋 tree。 |
| A11 | 每顆固定正方形；4 個 PHY 都在幾何中心；link 長度用中心距離 | PHY 位置是簡化幾何，不是真實封裝佈線 | link latency、link power、package area 受此假設影響。 |
| A12 | 每顆 power=0.15+0.85×0.75+0.03=0.8175 W；另加 link 長度×0.005 | 固定 utilization 功耗，沒有逐組活躍時間、idle/gating、memory／router activity、DVFS／溫度模型 | 同 N、同佈局的 OC/IC 有相同 A/P，策略差異主要只反映在 latency；不能宣稱已學到 workload-aware power 策略。 |
| A13 | link_dynamic_pj_per_bit=0.5 只用於每 inference bit-hop energy | 不加入目前 total_power_w 或 PPA power 約束；每 inference energy 不是瓦特 | 此值改動不會改變目前 power reward。若要平均動態 power，需定義活動率／工作排程；不代表必須要求使用者輸入 FPS。 |
| A14 | area 使用 chiplet placement 外框的 interposer/package area；另有 total_chiplet_area | 沒有 PE、SRAM、PHY 的 macro area 模型、PDN、keep-out、thermal／manufacturing constraints | 不能把這個 A 直接當「所有運算電路面積」。 |
| A15 | PE、SRAM、頻率、寬度、功耗係數可分別改 | 沒有把硬體容量與面積／功耗耦合 | **最需優先補強**：只增 PE 或 SRAM，固定 width/power 不變，會得到沒有同步付出 A/P 成本的收益。只升頻也不會自動增加功耗。 |
| A16 | FP32 bytes=元素數×4；ResNet 用公式生成 JSON | 未用真實 graph trace 或數值執行交叉驗證 mapping；其他 catalog 模型未做同等校驗 | 改 dtype 不能只改標籤，必須重算 tensor/weight/partial-sum bytes、吞吐量及精度／累加器需求。 |
| A17 | 每組固定一種策略；連續 block grouping；Head 不允許多顆；spatial 停用；channel 必須等分 | 這是目前支援範圍，非物理不可能定理；channel metadata=0 時會略過此項限制 | 搜尋空間排除了混合策略、非連續 grouping、不等分、FC parallel 與 spatial；不能推廣成全部合法 mapping。 |

## 三、RL 與實驗嚴謹性

| ID | 現況 | 需要承認的限制 |
| --- | --- | --- |
| R1 | 每次從頭建立 tabular Q-table，state 包含完整設計 prefix | 是單一任務內的搜尋／記憶，沒有跨模型、跨硬體或未見 preference 的政策泛化證據。 |
| R2 | 第一個 episode 使用最少 chiplet 起始候選；之後 epsilon-greedy；終端 PPA reward 反向更新；最後 observed-transition replay | 方法混合了啟發式起始、Q 更新與已取樣圖上的回放；最後 policy=best sampled reward 本身不能證明探索優於 random。 |
| R3 | 可行 reward=1/(1+weighted_cost)；不可行 reward=-1-V/(1+V)，V 是未加 preference 權重的超限比例總和 | **不可行候選的 Q reward 不含 preference**。相同上限時，換 latency/area/power 偏好，不保證在這個階段改變 Q 的決策；archive 的加權 cost 只在先前排序項目相同時解 tie。這是 constraint-first 選擇，不應描述成全程 preference-sensitive。 |
| R4 | 權重 0.8/0.1/0.1，balanced 均分；以 metric/limit 正規化 | 權重是設計選擇；改 PPA 上限也會改變 cost 比例，不只改可行性門檻。area 與固定 power 常高度受顆數共同控制。 |
| R5 | epsilon 每 episode 衰減，包括命中 cache 的 episode；連續 50 次無新設計強制探索 | 可能在取得足夠新設計前降低探索；50、0.99 等均為未充分調參的選擇。 |
| R6 | 固定 learning rate 0.2、最多 500 sweeps；以 Q 更新量<1e-12 作 replay 終止條件 | 不是完整設計空間收斂證明；調極小 learning rate 時，小更新量也不等同小 Bellman residual。CLI 記錄 replay/policy flags，但沒有在所有非預設設定下強制成功。 |
| R7 | 預設 128 unique evaluations／最多 3000 episodes；空間約 20,176,298 個 | 預算有限，不保證找到可行解或全域最優；完整枚舉的最佳性只對受測的小型支援空間成立。 |
| R8 | 最終 0.3 頻寬三 seed：相同評估預算下對 random 一勝兩負；256 四偏好各一 seed，都保留相同起始候選 | 尚無穩定 RL 優勢、統計顯著性或充分多模型證據；也不能把找到的 256 可行解歸功於 RL 優於啟發式。 |
| R9 | official/local parity、traffic regression、Q-policy 測試通過 | 兩條評估路徑共用多項假設；一致性不是獨立物理校準，也未驗證 IC reduction 的數值誤差／accuracy。 |

## 四、工程層面還沒完全收尾的地方

| ID | 問題 | 影響 |
| --- | --- | --- |
| E1 | `avg_latency_ns` 是 E2E，但 `avg_latency_cycles` 仍填 Rapid ICI cycles；另有 `rapid_avg_latency_*` | 這兩個同名前綴欄位不能直接用 frequency 互換，容易在報表誤用。應重新命名或統一語義。 |
| E2 | `tools/run_mesh_redefinition_analysis.py` 仍引用已移除 FPS constants/helper；部分舊簡報工具讀取 target_fps | 歷史工具未全部遷移，部分與新介面不相容；主入口移除 FPS，不代表整個 repository 完全沒有舊 FPS 程式。 |
| E3 | 正式 Rapid 呼叫使用 validate=False，backend=auto 可 fallback | 當前有測試與 backend 標記，但未通過完整 upstream schema/technology 驗證；正式發表應固定引擎版本與 backend，補完整輸入驗證。 |
| E4 | manifest 記錄設定／模型／核心 Python source hash，但未完整鎖定外部 Rapid 程式與所有 dependency 版本 | 在另一台電腦重現仍有環境差異風險。 |
| E5 | graph validator 檢查 DAG、數值非負與部分 metadata；沒有完整 shape／operator 相容性驗證 | 不能將 JSON parser 稱為已完成通用 ONNX/PyTorch graph extraction；手改 metadata 可能通過檢查但語義不成立。 |
| E6 | `experiment.effective_link_bandwidth_bits_per_cycle` 是另存的描述值，真正計算用 `network.link_bandwidth_bits_per_cycle` | 只改 experiment 不改 network，不會改實際 bandwidth；兩欄可能失同步。 |
| E7 | packaging_yield=.9、bump_pitch=.05、non_data_wires=12、fraction_power_bumps=.5、PHY fraction=.25 等寫在 adapter | 是簡化／占位欄位，不能宣稱已依製程校準；本路徑預先指定 bandwidth，不能期待改 bump_pitch 就自動改吞吐量。 |
| E8 | 主入口與 legacy evaluator 的 PPA scoring 路徑不同；歷史 DP pool 保留舊 surrogate/pruning | 不應把不同入口、不同候選池的 score 或排名混用，也不能用舊簡報作新版本驗證。 |

## 五、目前可改的變量

### A. 一般使用者需求

| 變量 | 現值 | 修改方式 |
| --- | --- | --- |
| latency 上限 | 500000000 ns = 0.5 s | `ppa.max_latency_ns` 或 `--max-latency-ns` |
| area 上限 | 800 mm² | `ppa.max_area_mm2` 或 `--max-area-mm2` |
| power 上限 | 16 W | `ppa.max_power_w` 或 `--max-power-w` |
| preference | balanced | CLI `--preference balanced/latency/area/power`；自訂數值權重目前需要改程式或使用 Python profile API |

FPS 保持輸出指標，不恢復 target/minimum FPS。

### B. 平台設定：可改 JSON，但不代表硬體成本已自動一致

| 變量／欄位 | 現值 | 直接影響與限制 |
| --- | --- | --- |
| evaluation.max_chiplets | 16 | 搜尋上限、可行空間、可选 package；不是直接固定候選要使用 16 顆。 |
| chiplet.pe_rows / pe_cols | 8 / 8 | compute throughput；不會自動提高 width 或 power。 |
| chiplet.frequency_hz | 200000000 | compute 及 network bits/cycle→bits/s、cycle→seconds 一起改；不會自動改 power。 |
| chiplet.ops_per_pe_per_cycle | 2 | compute throughput；需與數值精度／PE 規格一致。 |
| chiplet.op_per_mac | 2 | operation 計數慣例；不能把它當免費提升效能的旋鈕，須和 throughput 定義一致。 |
| chiplet.utilization | 0.75 | 同時影響 compute throughput 與固定 dynamic power 項。 |
| chiplet.sram_mb | 16 MiB | mapping feasibility；目前不自動影響 chiplet area/power。 |
| chiplet.width_mm / spacing_mm | 8.79772697916911 / 0.15 | package 外框、link 長度、link latency/static power；width 不等同已校準電路規模。 |
| chiplet.internal_latency_cycles / phy_latency_cycles | 3 / 12 | path latency。 |
| network.link_bandwidth_bits_per_cycle | 0.3，每方向 | serialization、network FPS；256 只能作明確另列的 baseline。 |
| network.link_latency_base_cycles / link_latency_cycles_per_mm | 1 / 0.25 | `ceil(base + slope × length)`。 |
| power.chiplet_static_w / chiplet_peak_dynamic_w / phy_w | 0.15 / 0.85 / 0.03 W | 每顆固定 power；PHY 是 aggregate 項。 |
| power.link_static_w_per_mm | 0.005 | link 長度相關 power。 |
| power.link_dynamic_pj_per_bit | 0.5 | link energy/inference；不改目前 PPA power。 |
| rapidchiplet.root / backend | 本機 engine 路徑 / auto | 評估後端與 fallback 行為；不是效能最佳化變量。 |

### C. 搜尋超參數

| 變量 | 現值 | 可改方式／注意 |
| --- | --- | --- |
| evaluation_budget | 128 | search JSON 或 --budget；比較演算法應固定相同 expensive evaluation 預算。 |
| max_episodes | 3000 | search JSON 或 --episodes；episode≠unique evaluation。 |
| seed | 20260919 | search JSON 或 --seed；需要多 seed，不能只保留最好的一次。 |
| learning_rate | 0.2 | search JSON；會影響 online learning 與 replay。 |
| epsilon_start / end / decay | 0.8 / 0.05 / 0.99 | search JSON；目前以 episode 衰減。 |
| discount | 1 | 程式固定並拒絕其他值；避免不同 group 深度帶來終端回報折扣偏差，不是一般可自由調的參數。 |
| stagnant threshold / replay sweeps / tolerance | 50 / 500 / 1e-12 | 寫在程式，需改碼；尚未系統性校準。 |
| warm start、reward、weight presets | 最少 chiplet／constraint-first／固定權重 | 需改程式；變更後需重做公平 baseline 與多 seed 比較。 |

### D. 需要改程式或重建模型，不能只改一個 JSON 數字

數值精度與 accumulator 精度、輸入解析度、batch、block 邊界、混合策略／spatial、不等分 mapping、leader／collective 協定、placement、routing、topology 搜尋、精確 memory liveness、DRAM streaming、overlap、封包／queue 模型、PE/SRAM/PHY 的 area-power 耦合。

## 六、優先改善順序與實驗方式

1. 先固定平台與指標定義：PPA 的 A 是何種面積，power 是何種活動狀態，E2E 是否包含 off-chip I/O；統一 latency 欄位。
2. 補 hardware cost coupling，或在耦合完成前固定 PE、SRAM、width、power 為同一個不可拆開的假設平台，不把免費加硬體當 DSE 改善。
3. 對 OC/IC efficiency 做校準／消融；以獨立逐層成本證據代替人工偏好。
4. 驗證真實 tensor shape、memory lifetime 與 operator semantics，再擴大模型／mapping 支援。
5. 決定 constraint-first 與 preference 在不可行區域的需求；若需要偏好全程影響決策，改 reward 後再驗證，而不是宣稱目前已經做到。
6. 最後做 matched-budget、多 seed、多 workload 比較；同时呈現 median、分散程度、可行率與 runtime。把 regression 正確性、數值模型精度、搜尋品質分開報告。

可先規劃的敏感度測試（不是已執行或推薦硬體規格）：頻寬 0.3/1.5/16/64/256、budget 128/512/2048；mapping efficiency 使用現有值與全部 1 的消融；每組固定一批 seeds。SRAM 8/16/32 MiB 的掃描若尚無成本耦合，只能標示「容量敏感度」，不能當成公平硬體 PPA 比較。

## 程式證據

- [平台設定](C:/Users/user/Desktop/rapidchiplet/audit_0917_snapshot/simplified_rapidchiplet/configs/defaults.json)
- [Mapping／SRAM／效率](C:/Users/user/Desktop/rapidchiplet/audit_0917_snapshot/simplified_rapidchiplet/simple_rapidchiplet/mapping.py)
- [Tensor ownership／通訊協定](C:/Users/user/Desktop/rapidchiplet/audit_0917_snapshot/simplified_rapidchiplet/simple_rapidchiplet/communication.py)
- [E2E 與 FPS 近似](C:/Users/user/Desktop/rapidchiplet/audit_0917_snapshot/simplified_rapidchiplet/simple_rapidchiplet/e2e_latency.py)
- [Rapid adapter／power／area](C:/Users/user/Desktop/rapidchiplet/audit_0917_snapshot/simplified_rapidchiplet/simple_rapidchiplet/rapidchiplet_engine.py)
- [RL reward／搜尋](C:/Users/user/Desktop/rapidchiplet/audit_0917_snapshot/simplified_rapidchiplet/simple_rapidchiplet/preference_dse.py)
- [ResNet metadata 生成器](C:/Users/user/Desktop/rapidchiplet/audit_0917_snapshot/simplified_rapidchiplet/tools/calibrate_resnet50.py)
- [已有實驗證據](C:/Users/user/Desktop/rapidchiplet/audit_0917_snapshot/simplified_rapidchiplet/VALIDATION_0917_zh-TW.md)
