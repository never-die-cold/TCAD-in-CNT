# CNTFET TID：用户操作与数据溯源指南

本文面向已经安装 Sentaurus W-2024.09 虚拟机、准备开始器件仿真的用户，说明从文献数据到 CNTFET TID 分析的操作流程。`tcad/cntfet/topgate/` 当前处于参数补齐阶段；工具链验证使用 `tcad/smoke/` 硅二极管工程。

## 1. 你和 Agent 分别做什么

| 工作 | 你 | Agent |
| --- | --- | --- |
| 阅读论文、确认图表与单位 | 必须参与并最终确认 | 提供文献清单和核对提示 |
| 图 2/图 3 数字化 | 操作 WebPlotDigitizer 并抽查数据点 | 校验 CSV、转换格式 |
| 缺失材料参数与假设 | 决定采用哪篇文献或哪项假设 | 检查是否缺项、是否无来源 |
| 生成 SWB 输入 | 运行一条准备命令 | 维护模板和生成器 |
| 首次 SDE/SDevice | 在虚拟机 SWB 中运行 | 根据日志解释错误 |
| 网格与零剂量验收 | 在 SVisual 中检查并决定通过与否 | 生成对比图和误差表 |
| 首批 TID | 确认零剂量通过后运行 | 准备固定电荷/陷阱输入 |
| 批量扫描 | 明确批准后执行 | 自动化、汇总失败点和结果 |

你确认文献估计值的状态与用途；零剂量验收通过后启动 TID 批量矩阵。

## 2. 文件和目录在哪里

宿主机项目根目录是 `E:\2_项目代码\05_科研仿真\TCAD in CNT`。

| 位置 | 内容 | 是否由你编辑 |
| --- | --- | --- |
| `reference/literature/electronics-12-01000.pdf` | Cui 2023 原文，本地归档 | 只读 |
| `data/literature/cui2023_topgate/source.md` | 已核实的结构、辐照条件、图表位置 | 发现理解错误时修正 |
| `device_parameters.csv` | 已报告值与缺失值清单 | 为新参数补来源，不只填数值 |
| `idvg_raw.csv` | 图 2 的原始有符号数字化数据 | 是 |
| `metrics_raw.csv` | 图 3a–c 的阈值、跨导、摆幅 | 是 |
| `configs/tcad/cntfet_topgate.toml` | 实际用于生成 deck 的几何、材料、偏置和网格 | 是，填完所有 `REQUIRED` |
| `tcad/cntfet/topgate/` | SDE/SDevice/材料模板 | 通常由 Agent 维护 |
| `results/tcad/` | 生成的 deck、回传曲线、日志和分析 | 本地生成目录 |
| 虚拟机 `/home/tcad/STDB/cnt_tid` | 建议的 SWB 工程和原生输出目录 | 你在 SWB 中操作 |

每次准备完成后，`tcad_project_metadata.json` 会记录配置、模板和文献 CSV 的 SHA-256。每次导出 `.plt` 时，同名 JSON 会记录原始 `.plt` 的 SHA-256。

## 3. 第一步：数字化论文数据

### 3.1 图 2：多剂量 Id–Vg

1. 打开本地 PDF 第 4 页图 2。该图是 `VDS = −0.1 V`，包含 0、200、500、1000、2000、3000 krad(Si) 六条曲线。
2. 在 WebPlotDigitizer 中校准 VGS 横轴和 IDS 对数纵轴，按对数坐标提取电流。
3. 先提取零剂量曲线，再提取至少两个非零剂量曲线。保留原始负 VGS、负 VDS、负 IDS。
4. 将点追加到 `data/literature/cui2023_topgate/idvg_raw.csv`，保持列名不变。
5. `source_location` 填 `Figure 2 page 4`，`scan_direction` 在原文未明确时填 `not_reported`。
6. 每条曲线至少抽查三个点。复核前 `quality=pending_digitization`，复核后改为 `verified`；转换器会拒绝未复核数据。

转换为现有紧凑标定器使用的正幅值格式：

```bash
cnt-tid tcad-prepare-data \
  --input data/literature/cui2023_topgate/idvg_raw.csv \
  --output results/tcad/literature/idvg_magnitude.csv
```

P 型器件使用 `Vsg=−VGS`、`Vsd=−VDS`、`|Id|=−IDS`。图 2 的 VGS 正半段对应负 Vsg，现有标定器不接受，因此会排除并报告这些点；原始 CSV 不丢数据。剂量单位保持 `krad(Si)`，不会自动改成 `krad(SiO2)`。

### 3.2 图 3：独立指标

在 `metrics_raw.csv` 中分别填写图 3a 的 `threshold_signed_v`、图 3b 的 `gm_max_s`、图 3c 的 `ss_mv_dec`，仅录入可复核的数值。图 3 的摆幅先下降后上升，采用非单调或分段模型描述。

## 4. 第二步：填写实际仿真配置

打开 `configs/tcad/cntfet_topgate.toml`。所有 `REQUIRED` 都必须由你根据新文献或明确假设填写，包括：

- CNT 网络等效厚度、介电常数、带隙、电子亲和能；
- 等效三维态密度 `Nc300/Nv300` 和电子/空穴迁移率；
- Y2O3/HfO2 串联等效介电常数；
- 栅功函数、源漏延伸、截断衬底厚度；
- 全局和沟道网格尺寸。

已给出的论文值包括栅长 4 µm、宽度 30 µm、顶栅介质总厚度 10 nm、埋氧 280 nm、VDS = −0.1 V 和剂量单位 krad(Si)。`temperature_k=300` 是数值假设，论文只写“室温”。

二维模型用 `AreaFactor=30` 将电流缩放到论文宽度。`CNTNetwork` 和 `TopDielectric` 分别代表有效半导体与等效介质栈。新增参数的来源同时写入 `device_parameters.csv` 或新的文献目录。

全部填写后运行：

```bash
cnt-tid tcad-prepare \
  --config configs/tcad/cntfet_topgate.toml \
  --output results/tcad/prepared
```

仍有缺项时命令会列出字段并拒绝生成。生成成功只表示模板替换完成，状态仍是 `prepared_not_run`，不表示语法、收敛或物理结果已验证。

## 5. 第三步：你在 SWB 中运行零剂量

将以下生成文件复制到虚拟机 `/home/tcad/STDB/cnt_tid`：

- `sde_dvs.cmd`
- `sdevice_des.cmd`
- `sdevice.par`
- `datexcodes.txt`
- `tcad_project_metadata.json`

可使用 VMware 共享文件夹；虚拟机密码通过环境变量管理。

在虚拟机中：

1. 打开终端并运行 `swb`。
2. 新建或打开 `/home/tcad/STDB/cnt_tid` 工程。
3. 添加 **SDE** 工具节点，输入选择 `sde_dvs.cmd`。
4. 添加 **SDevice** 工具节点并连接到 SDE 后面，命令文件选择 `sdevice_des.cmd`，参数文件选择 `sdevice.par`。
5. 确保 `datexcodes.txt` 对两个工具的运行目录可见。若节点目录没有该文件，将它复制到 SWB 属性显示的实际节点运行目录；否则会出现材料未定义错误。
6. 先只运行 **SDE**。成功后打开生成的 `n*_msh.tdr`，在 SVisual 中检查：沟道、等效顶栅介质、埋氧、衬底和四个接触的位置；网格是否在薄沟道与界面处足够细。
7. 确认结构后运行 **SDevice**。模板中的 `@tdr@`、`@plot@`、`@tdrdat@`、`@log@` 由 SWB 展开并保留。
8. 打开 `n*_des.log`，确认出现 `Curve trace finished.` 和 `Sentaurus Device simulation finished`。只有进程返回成功但日志不完整时，仍按失败处理。
9. 用 SVisual 打开 `n*_des.plt`，检查 gate/drain 电压和 drain TotalCurrent，以论文图 2 的零剂量曲线为基准。

首次运行保留所有日志和失败点，按实际偏置、收敛状态与剂量单位分析曲线。

## 6. 第四步：回传并检查零剂量结果

将零剂量 `.plt` 和日志复制到宿主机 `results/tcad/zero_dose/`，然后运行：

```bash
cnt-tid tcad-export \
  --plt results/tcad/zero_dose/n2_des.plt \
  --output results/tcad/zero_dose/idvg_signed.csv
```

节点号以你的 SWB 工程为准。导出的 CSV 保留 SDevice 有符号端电压和电流，同名 JSON 保存原始 `.plt` 校验和。

零剂量验收需要同时满足：

- 所有偏置点求解完成，失败点有日志；
- 电流方向、量级、阈值和亚阈值趋势合理；
- 至少三档网格的关键指标变化已记录；
- 与论文图 2 零剂量曲线的误差和系统偏差已解释；
- 你明确同意进入 TID 阶段。

## 7. 第五步：经你批准后才做 TID

首阶段 TID 采用等效固定电荷/界面陷阱模型：

```text
Physics (MaterialInterface = "CNTNetwork/TopDielectric") {
  Traps(Conc = <由剂量标定的面密度 cm-2> FixedCharge)
}
```

`Conc` 的正负表示电荷符号。第一版使用总有效固定电荷，并单独比较跨导和摆幅退化；`Qot(D)` 与 `Qit(D)` 的拆分需要额外数据。

你在 SWB 中先运行 200 和 500 krad(Si) 两个点，检查阈值漂移方向和收敛，再决定是否运行完整剂量矩阵。图 3c 的非单调摆幅采用额外机制或分段模型描述。

## 8. 常见问题定位

| 现象 | 优先检查 |
| --- | --- |
| `CNTNetwork` 或 `TopDielectric` 未定义 | 节点运行目录是否包含 `datexcodes.txt` |
| 找不到网格 | SDE 是否成功、SDevice 是否连接为下一节点、`@tdr@` 是否保留 |
| 材料参数缺失 | `sdevice.par` 是否加入节点、配置中的所有 `REQUIRED` 是否已填 |
| 电流差 30 倍 | `Physics AreaFactor` 是否为论文宽度 30 µm |
| 剂量单位相差 1000 倍 | krad 与 rad、rad(Si) 与 rad(SiO2) 是否混淆 |
| 返回码为 0 但结果不完整 | 日志中的两个完成标记、最后一个偏置点和 `.plt` 行数 |
| 零剂量拟合始终偏差很大 | 先检查有效介质/接触/扫描方向假设，并保持 TID 参数为零 |

## 9. 运行前提与下一步

运行前提：完成图 2 数据提取、补齐 `REQUIRED` 参数并生成 deck。下一步：**先数字化零剂量曲线并复核，然后补齐一份有出处的材料参数表。**
