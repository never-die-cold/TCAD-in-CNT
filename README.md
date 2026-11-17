# TCAD-in-CNT

面向**碳纳米管场效应晶体管（CNTFET）与碳基 CMOS 集成电路总电离剂量（TID）效应**的可复现仿真项目。当前版本打通“器件剂量扫描 → 电学退化 → 反相器静态特性”的最小闭环，并提供已在 Sentaurus W-2024.09 虚拟机中验证的 SDE/SDevice 冒烟接口。

> **模型范围：当前版本实现“剂量—陷阱电荷—紧凑电学参数—电路响应”的等效链路。** 默认剂量系数用于流程验证，器件寿命与抗辐射指标的定量评估以实验或 TCAD 标定为前提。

## 当前能力

- 以氧化层陷阱电荷 `Qot` 和界面陷阱电荷 `Qit` 驱动阈值漂移；
- 用剂量相关迁移率和斜率因子描述驱动能力及亚阈值特性退化；
- 扫描 n/p CNTFET 转移特性，输出 `Ion`、`Ioff`、最大跨导等指标；
- 求解互补 CNTFET 反相器 VTC，提取 `VM`、`VIL`、`VIH`、`NML`、`NMH`；
- **标定模式**：从 `data/calibration_template.csv` 格式的实测/TCAD 曲线拟合剂量系数，含留一剂量点交叉验证，输出可直接回灌的 TOML 配置；
- **敏感性分析**：对关键参数做 ±10% 逐个扰动（OAT），输出归一化灵敏度表和龙卷风图；
- **几何实验矩阵**：联合扫描栅氧厚度与栅长，保留每个场景的完整曲线、配置指纹、警告与失败日志；
- **TCAD 冒烟接口**：通过 `vmrun` 自动执行已验证的 SDE/SDevice 工程并回传日志；当前验证对象为硅二极管；
- 一键输出 CSV、元数据 JSON 和 PNG 图，配置采用严格 TOML 校验；
- 自动测试覆盖阈值漂移方向、电流边界、反相器电平、标定还原、灵敏度符号和完整运行流程。

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

CNTFET 方向已建立 Cui 2023 顶栅 P 型 CNT 网络器件的数据清单和 SWB 模板，当前处于参数补齐阶段。论文图表数据、缺失参数和用户操作位置见 [数据说明](data/literature/cui2023_topgate/source.md) 与 [CNTFET 用户指南](docs/tcad-user-guide.md)。用户依据文献或明确假设填写 `configs/tcad/cntfet_topgate.toml` 中的 `REQUIRED` 后，即可生成供 SWB 检查的 deck。

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

## 仓库结构

```text
configs/             器件、剂量与电路配置
data/                实测/TCAD 标定数据模板
docs/                模型假设、实验矩阵与研发计划
src/cnt_tid/         可复用 Python 模型和命令行流程
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
