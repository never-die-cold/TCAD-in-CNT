# TCAD-in-CNT

面向**碳纳米管场效应晶体管（CNTFET）与碳基 CMOS 集成电路总电离剂量（TID）效应**的可复现仿真项目。当前版本打通“器件剂量扫描 → 电学退化 → 反相器静态特性”的最小闭环，并为 Sentaurus 等 TCAD 求解器预留标定与数据接口。

> **状态声明：v0.1 是可运行的等效紧凑模型基线，不是已完成标定的三维量子 TCAD 模型。** 默认剂量系数仅用于验证流程，不能直接用于器件寿命预测或抗辐射指标声明。

## 当前能力

- 以氧化层陷阱电荷 `Qot` 和界面陷阱电荷 `Qit` 驱动阈值漂移；
- 用剂量相关迁移率和斜率因子描述驱动能力及亚阈值特性退化；
- 扫描 n/p CNTFET 转移特性，输出 `Ion`、`Ioff`、最大跨导等指标；
- 求解互补 CNTFET 反相器 VTC，提取 `VM`、`VIL`、`VIH`、`NML`、`NMH`；
- 一键输出 CSV、元数据 JSON 和 PNG 图，配置采用严格 TOML 校验；
- 自动测试覆盖阈值漂移方向、电流边界、反相器电平和完整运行流程。

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

## 输出文件

| 文件 | 内容 |
| --- | --- |
| `device_transfer.csv` | 各剂量下 n/p 器件的转移曲线 |
| `inverter_vtc.csv` | 反相器电压传输曲线及增益 |
| `summary.csv` | 阈值、电荷、迁移率、开关阈值与噪声容限 |
| `metadata.json` | 完整配置、剂量单位、模型类型与标定状态 |
| `device_transfer.png` | 器件转移特性图 |
| `inverter_vtc.png` | 反相器 VTC 图 |
| `degradation_metrics.png` | 阈值与电路静态指标随剂量变化 |

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

当前等效模型不包含肖特基接触、量子电容、NEGF 输运、直接带间隧穿、陷阱时间动力学及辐照偏置历史。两周内优先完成：

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
