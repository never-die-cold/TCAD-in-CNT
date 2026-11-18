# TCAD-in-CNT

面向**碳纳米管场效应晶体管（CNTFET）与碳基 CMOS 集成电路总电离剂量（TID）效应**的可复现仿真项目。当前版本打通"文献锚定标定 → 器件/反相器/环振退化 → 全链条不确定性量化 → 跨结构迁移预测 → 退火情景"的完整链路，并提供已在 Sentaurus W-2024.09 虚拟机中验证的 SDE/SDevice 冒烟接口与 CNTFET deck 生成器。

> **模型范围：**"剂量—陷阱电荷—紧凑电学参数—电路响应"为经文献图表标定的等效紧凑模型（`calibrated_compact_fit_metrics`），不是器件预测；退火与剂量率为显式假设情景。器件寿命与抗辐射指标的定量评估以实验或 TCAD 标定为前提。

## P0 结项成果（v0.13.0）

```bash
cnt-tid p0        # 主线：标定 → 扫描 → 验证 → 图 1–3、11 + manifest
cnt-tid all       # 一键全量重建：p0 → 蒙特卡洛 → 迁移预测 → 退火情景（约 6 分钟）
```

| 环节 | 产物 |
| --- | --- |
| 结构冻结 | `configs/p0/cntfet_tid_p0.toml`、[图 1](docs/figures/p0/fig1_structure.png)、`data/parameters/tid_parameters.csv` |
| 参数溯源 | `scripts/digitize_cui2023_fig3.py` → `data/literature/cui2023_topgate/fig3_metrics_digitized.csv` → `results/p0/parameters_resolved.csv` |
| 标定/验证 | [图 2](docs/figures/p0/fig2_validation.png)（含两阶段摆幅分解）、`results/p0/calibration/` |
| 器件+反相器扫描 | [图 3](docs/figures/p0/fig3_inverter.png)、[图 11](docs/figures/p0/fig11_device_family.png)、`results/p0/dose_sweep/` |
| 敏感性/不确定性 | [图 4](docs/figures/p0/fig4_sensitivity.png)、[图 5](docs/figures/p0/fig5_robustness.png)、**[图 8](docs/figures/p0/fig8_mc.png)（全链条蒙特卡洛置信带，`cnt-tid mc`）** |
| 跨文献校验与迁移 | [图 6](docs/figures/p0/fig6_cross_source.png)、**[图 9](docs/figures/p0/fig9_prediction_bands.png)（结构迁移预测器，`cnt-tid predict`）** |
| 电路级退化 | **[图 7](docs/figures/p0/fig7_ringosc.png)（准静态环振，`cnt-tid ringosc`）**、**[图 10](docs/figures/p0/fig10_annealing.png)（退火情景，`cnt-tid anneal`）** |
| 可复现 | `results/p0/manifest.json`；一键全量重建的总清单 `results/deliverable/deliverable_manifest.json`（`cnt-tid all`） |

关键结果：剂量律指数 p = 0.482；3 Mrad(Si) 下 |ΔVth| = 1.108 V、反相器 VM 1.000 → 0.133 V；摆幅两阶段律（生成 − 退火）复现 200 krad 谷，残差 27.7 → **17.9 mV/dec**（全点 ≤1.1σ）；**11 级环振频率坍缩 10.6×（4.23 MHz → 399 kHz），静态功耗 ×385**；蒙特卡洛给出电路级数字的 5–95 % 置信带（VM@3Mrad 0.024–0.308 V——电路级结论高度条件于假设）；跨结构指数 0.23–0.85，单锚点迁移后类别带每 10 倍剂量仍有 **4.1×** 形状不确定性。**TID 参数必须绑定结构。**

完整推导、验证与局限见 **[P0 结项报告](docs/p0-report.md)**。

## 当前能力

- 以氧化层陷阱电荷 `Qot` 和界面陷阱电荷 `Qit` 驱动阈值漂移（幂律 Q = k·D^p）；
- **两阶段摆幅通道**：界面态密度 = 生成幂律 − 饱和退火，复现 200 krad 摆幅谷；与阈值电荷通道解耦；
- 器件转移特性（`Ion`/`Ioff`/Gm）、互补反相器 VTC（`VM`/`VIL`/`VIH`/`NML`/`NMH`）、**准静态环振频率与功耗预算**（`cnt-tid ringosc`）；
- **辐照后退火情景**（`cnt-tid anneal`）：注册表假设的分式指数恢复，VM/摆幅/频率的恢复曲线；
- **全链条蒙特卡洛**（`cnt-tid mc`）：registry 假设三角采样 + 数字化误差棒正态采样 → 关键数字的置信区间，失败抽样如实计数；
- **结构迁移预测器**（`cnt-tid predict`）：每变体 |ΔVt|(D) 预测 + 架构类别包络带 + 外推标记；
- 标定模式（曲线级 + 指标级两条路径，含留一交叉验证）、敏感性分析、几何实验矩阵；
- **TCAD 集成**：冒烟链路、CNTFET deck 生成（`tcad-prepare`）、零剂量对齐（`tcad-align`，三项指标均 <20 %）与三档网格验证；
- 一键输出 CSV/JSON/PNG，配置严格 TOML 校验；100 项自动测试 + ruff 全绿。

## 快速开始

要求 Python 3.11 或更高版本。

```bash
python -m pip install -e ".[dev]"
cnt-tid run --config configs/baseline.toml --output results/baseline
```

也可以不安装命令行入口：

```bash
PYTHONPATH=src python -m cnt_tid run --config configs/baseline.toml --output results/baseline
```

Windows PowerShell 可使用：

```powershell
$env:PYTHONPATH = "src"
python -m cnt_tid run --config configs/baseline.toml --output results/baseline
```

运行测试与静态检查：

```bash
pytest
ruff check src tests
```

### 标定：从实测曲线拟合剂量系数

```bash
cnt-tid calibrate --data data/calibration_template.csv \
    --config configs/baseline.toml --output results/calibration
```

输入数据遵循 `data/calibration_template.csv` 约定（正的端电压幅值、单一剂量单位、零剂量参考曲线、至少两个非零剂量点）。输出 `fitted_config.toml`（拟合后的完整配置，`calibration_status = "calibrated_compact_fit"`）、`calibration_summary.csv`（每个剂量点拟合出的阈值/迁移率/斜率因子）和 `calibration_report.json`（含留一剂量点阈值残差）。随后可直接用拟合配置重跑主流程：

```bash
cnt-tid run --config results/calibration/fitted_config.toml --output results/calibrated
```

标定器按“亚阈值摆幅退化折算界面陷阱”的启发式，将总阈值漂移线性斜率拆分为 `Qot`/`Qit`，用于紧凑参数估计；陷阱谱的独立识别需要额外测量数据。

### 敏感性分析

```bash
cnt-tid sensitivity --config configs/baseline.toml --output results/sensitivity
```

对 12 个关键参数（两个器件的阈值、迁移率、`Qot`/`Qit` 斜率、迁移率退化和摆幅退化系数）做 ±10% 逐个扰动，输出 `sensitivity.csv`、`sensitivity_baseline.csv` 和 `sensitivity_tornado.png`。可用 `--magnitude` 调整扰动幅度、`--params` 指定参数子集。

### 几何实验矩阵

```bash
cnt-tid matrix --config configs/baseline.toml --output results/matrix \
    --oxide-scales 0.8 1.0 1.2 --length-scales 0.8 1.0 1.2
```

对两种几何倍率做笛卡尔积，并同步缩放 n/p 器件；每个场景执行完整剂量扫描。默认 3×3 矩阵对应实验计划中的几何 ±20% 扰动。`matrix_summary.csv` 汇总所有成功场景，`matrix_manifest.csv` 记录通过/失败状态；失败场景保留 `failure.txt`，警告写入 `warnings.txt`，不会因单点失败而跳过其余场景。存在失败场景时 CLI 返回非零退出码。

`metadata.json` 和 `matrix_metadata.json` 中的 `config_sha256` 是规范化有效配置的 SHA-256，与 TOML 空格或字段顺序无关，可用于核对结果与配置是否一致。

### Sentaurus 虚拟机冒烟

虚拟机启动且 VMware Tools 正常后，设置 `TCAD_VMRUN`、`TCAD_VMX` 和 `TCAD_GUEST_PASSWORD`，再运行：

```bash
cnt-tid tcad-smoke --output results/tcad-smoke
```

该命令执行 `tcad/smoke/` 中的三维硅二极管 SDE/SDevice 工程，检查收敛完成标记并回传日志与电流输出。它只验证 TCAD 工具链，不代表 CNTFET 或 TID 模型已经验证。完整连接说明见 [TCAD 接口](tcad/README.md)。

CNTFET 方向已完成 Cui 2023 顶栅 P 型 CNT 网络器件的 SDE/SDevice 零剂量首跑与三档网格检查。基准网格上 SS、Gm、恒流阈值相对紧凑模型的偏差分别为 5.5%、2.6%、12.5%，均通过 <20 % 门禁。0–3000 krad(Si) 六剂量点矩阵已完成；最终固定电荷 + 剂量相关界面态模型保持迁移率恒定，阈值、Gm、SS 相对文献最大偏差为 16.9%、13.3%、13.1%。参数溯源见 [数据说明](data/literature/cui2023_topgate/source.md)，结果位置与后续 TID 操作见 [CNTFET 用户指南](docs/tcad-user-guide.md)。

## 输出文件

### `cnt-tid run`

| 文件 | 内容 |
| --- | --- |
| `device_transfer.csv` | 各剂量下 n/p 器件的转移曲线 |
| `inverter_vtc.csv` | 反相器电压传输曲线及增益 |
| `summary.csv` | 阈值、电荷、迁移率、开关阈值与噪声容限 |
| `metadata.json` | 完整配置、剂量单位、模型类型与标定状态 |
| `device_transfer.png` | 器件转移特性图 |
| `inverter_vtc.png` | 反相器 VTC 图 |
| `degradation_metrics.png` | 阈值与电路静态指标随剂量变化 |

### `cnt-tid calibrate`

| 文件 | 内容 |
| --- | --- |
| `fitted_config.toml` | 拟合后的完整仿真配置，可直接用于 `cnt-tid run` |
| `calibration_summary.csv` | 每个（器件, 剂量）点拟合的紧凑参数及拟合残差 |
| `calibration_report.json` | 剂量系数、极性拆分说明、留一验证残差 |

### `cnt-tid sensitivity`

| 文件 | 内容 |
| --- | --- |
| `sensitivity.csv` | 参数 × 方向 × 指标的灵敏度长表 |
| `sensitivity_baseline.csv` | 未扰动的基准指标随剂量变化 |
| `sensitivity_tornado.png` | 最大剂量处 VM/NML/NMH 的龙卷风图 |

### `cnt-tid matrix`

| 文件 | 内容 |
| --- | --- |
| `matrix_summary.csv` | 所有成功场景的几何、剂量与器件/电路指标 |
| `matrix_manifest.csv` | 每个场景的状态、输出路径、警告路径与错误摘要 |
| `matrix_metadata.json` | 矩阵定义、基础配置、配置指纹和通过/失败计数 |
| `matrix_metrics.png` | 最大剂量处 VM/NML/NMH 的几何倍率热图 |
| `runs/<场景>/` | 与单次 `run` 相同的完整曲线、摘要、图和元数据 |

### `cnt-tid p0`（结项流水线）

| 文件 | 内容 |
| --- | --- |
| `config_resolved.toml` | 由参数注册表 + 标定结果生成的完整配置，可直接用于 `cnt-tid run` |
| `parameters_resolved.csv` | 全部参数、溯源类别（reported/digitized/derived/assumed/calibrated）、来源与不确定性 |
| `calibration/` | 残差表、留一剂量点验证、完整标定报告 |
| `dose_sweep/` | 与 `run` 相同的曲线、指标、元数据与图 |
| `validation/` | 模型与数字化文献指标的逐点对照 |
| `sensitivity/`、`robustness/` | OAT 弹性与假设区间扫描 |
| `figures/`、`docs/figures/p0/` | 结项图 1–3、11（其余图由独立命令生成，见下） |
| `manifest.json` | 软件版本、输入/输出 SHA-256 |

### 结项扩展命令（v0.8.0–v0.11.0）

```bash
cnt-tid ringosc     # 准静态 11 级环振：频率坍缩 + 静态/动态功耗（图 7）
cnt-tid mc          # 全链条蒙特卡洛：关键数字的 5-95 % 置信带（图 8，约 4 分钟）
cnt-tid predict     # 结构迁移预测：8 变体 |ΔVt|(D) + 架构类别包络带（图 9）
cnt-tid anneal      # 辐照后退火情景：VM/摆幅/频率恢复曲线（图 10）
cnt-tid all         # 一键全量重建 + 总清单 deliverable_manifest.json
cnt-tid tcad-align  # TCAD 零剂量曲线 vs 紧凑模型 <20 % 门禁
cnt-tid tcad-reproduce  # 零剂量 + 网格 + 六剂量点双模型 + SHA-256 manifest
```

每个命令把假设与溯源写进产物元数据；`mc` 与 `anneal` 的数字是显式假设情景，引用时必须连同假设值一起引用。

## 仓库结构

```text
configs/             器件、剂量与电路配置（configs/p0 = 结项冻结配置）
data/                实测/TCAD 标定数据模板、参数注册表、文献数字化结果
docs/                模型假设、实验矩阵与研发计划
src/cnt_tid/         可复用 Python 模型和命令行流程
scripts/             文献图表矢量化数字化脚本
tcad/                外部 TCAD 求解器接口约定
tests/               单元测试与端到端回归测试
.github/workflows/   持续集成
```

## 物理边界与优先级

当前等效模型聚焦氧化层/界面等效陷阱、剂量相关输运和静态电路响应。肖特基接触、量子电容、NEGF 输运、直接带间隧穿、陷阱时间动力学及辐照偏置历史列为后续扩展。两周内优先完成：

1. 选定一种顶栅或 GAA CNTFET 结构，冻结几何和材料参数；
2. 用辐照前 `Id–Vg` 曲线校准紧凑模型与 TCAD 静电/输运模型；
3. 用至少两个非零剂量点标定 `Qot(D)`、`Qit(D)` 和迁移率退化；
4. 完成器件—反相器联合剂量扫描与敏感性分析；
5. 若时间允许，再扩展到环形振荡器或标准单元，不牺牲标定质量。

详见 [两周研发计划](docs/roadmap.md)、[模型说明](docs/modeling.md) 和 [TCAD 接口](tcad/README.md)。

## 参考资料

- Cui et al., *Effect of Trapped Charge Induced by Total Ionizing Dose Radiation on the Top-Gate Carbon Nanotube Field Effect Transistors*, Electronics 12(4), 1000, 2023. https://doi.org/10.3390/electronics12041000
- Lee et al., *A Compact Virtual-Source Model for Carbon Nanotube FETs in the Sub-10-nm Regime*, IEEE Transactions on Electron Devices, 2015. https://doi.org/10.1109/TED.2015.2457424
- Stanford Nanoelectronics Lab, VS-CNFET Model. https://nano.stanford.edu/downloads/vs-cnfet-model

## 许可

MIT，详见 `LICENSE`。
