# TCAD 求解器接口

本目录约定外部 TCAD 工具与本项目的数据边界。已在 Sentaurus **W-2024.09** 虚拟机中实际验证 `tcad/smoke/`：SDE 生成三维硅二极管网格，SDevice 完成 Poisson–电子–空穴耦合和 0.1 V 偏置扫描。验证范围覆盖求解器、许可和数据链路。

## 从宿主机运行已验证的冒烟工程

要求虚拟机已启动、VMware Tools 正在运行，并且宿主机可执行 `vmrun`。在 Git Bash 中设置：

```bash
export TCAD_VMRUN="/d/VMware Workstation/vmrun.exe"
export TCAD_VMX='D:\TCAD_VM\T2024-09\Sentaurus2019.vmx'
export TCAD_GUEST_USER=tcad
export TCAD_GUEST_PASSWORD='替换为来宾机密码'
cnt-tid tcad-smoke --output results/tcad-smoke
```

也可通过 `--vmrun`、`--vmx`、`--guest-user` 和 `--guest-workdir` 指定连接参数。密码通过 `TCAD_GUEST_PASSWORD` 注入，与 TOML、源码和命令历史分离。脚本通过 `vmrun` 复制 `sde_dvs.cmd` 与 `sdevice_des.cmd`，依次运行 SDE 和 SDevice，并回传求解日志及 `.plt` 电流文件；`tcad_smoke_metadata.json` 保存 deck 的 SHA-256。原生 `.tdr` 保留在来宾工作目录，默认是 `/home/tcad/STDB/cnt_tid_smoke`。

运行成功必须同时满足：`vmrun` 返回码为 0、日志包含 `Curve trace finished.` 和 `Sentaurus Device simulation finished`。任一步失败都会中止后续步骤并报告 `vmrun` 输出，不会把失败点标记为成功。CI 只测试宿主机自动化逻辑，不假定拥有 Sentaurus 许可或虚拟机。

## CNTFET 工程状态与用户操作

`tcad/cntfet/topgate/` 已建立面向 Cui 2023 P 型 CNT 网络器件的 SWB 模板，当前处于参数补齐阶段。W-2024.09 不带 `CarbonNanotube`/`Graphene` 内置材料，因此模板使用本地 `datexcodes.txt` 定义有效 `CNTNetwork` 和 `TopDielectric`，所有输运参数必须显式提供。数据来源见 `data/literature/cui2023_topgate/source.md`，你在 SWB 中的逐步操作见 [CNTFET 用户指南](../docs/tcad-user-guide.md)。

## 推荐实现顺序

1. **结构**：在 Sentaurus Structure Editor 中建立顶栅或 GAA 几何。分别记录 CNT 有效材料、肖特基接触和量子修正的来源与模型设置。
2. **零剂量校准**：先对齐 `Id–Vg`，再引入辐射模型。网格、输运和接触参数均需记录。
3. **TID 建模**：优先使用经数据标定的氧化层固定电荷和界面陷阱；若使用求解器内建 Radiation/Gamma 模型，需按所用版本手册验证语法、材料处理和陷阱动力学。
4. **器件扫描**：导出统一 CSV，再交给本项目的指标提取与电路模块。
5. **混合模式**：仅在 n/p 器件分别验证后，将两者放入反相器混合模式仿真。

## 数据交换

`results/<run>/summary.csv` 中已有每个剂量点的：

- `n_qot_c_cm2`、`p_qot_c_cm2`：氧化层陷阱面电荷密度；
- `n_qit_c_cm2`、`p_qit_c_cm2`：界面陷阱电荷面密度；
- 阈值幅值、迁移率与斜率因子。

这些量可作为 TCAD 固定电荷/陷阱模型的候选初值。面电荷转换为体电荷时，先指定作用厚度，再计算相应的体浓度。

外部 TCAD 输出建议使用 `data/calibration_template.csv` 的格式，并额外保留原生 `.tdr`、`.plt` 和运行日志。原生大文件不直接提交 Git。

## 验收门槛

- 零剂量曲线校准后再谈辐射退化；
- 至少两个非零剂量点参与标定，另留一个点验证；
- 报告网格收敛、失败偏置点及参数来源；
- 任何结果图都注明“实测标定”“文献参数”或“演示未标定”。
