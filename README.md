# Solar Tariff Roller

消纳电价计算工具项目骨架。

当前目录结构围绕以下目标设计：

- 使用 Python 构建可复用的测算与反算引擎
- 支持 Excel 模板导入、结果导出
- 预留 API / Web 接入层，便于后续扩展为内部工具

## 目录结构

```text
src/solar_tariff_roller/
  api/           接口层，后续可接 FastAPI
  models/        领域模型
  schemas/       输入输出数据结构
  services/
    calc/        发电、收益、税费、现金流计算
    parser/      Excel/CSV 导入解析
    solver/      IRR 目标反算
    exporter/    结果导出
  utils/         通用工具
tests/           测试代码
docs/            需求、公式、设计文档
data/
  raw/           原始输入文件
  templates/     标准模板
  processed/     中间处理结果
  exports/       导出结果
scripts/         开发辅助脚本
```

## 建议的下一步

1. 明确标准输入模板字段
2. 把现有 Excel 公式拆成 Python 计算模块
3. 建立 Excel 与 Python 的结果对账测试

## 当前输入模型范围

第一版标准输入已经按以下模块拆分：

- `project`: 项目基础信息
- `generation`: 发电假设参数
- `consumption`: 消纳与上网拆分参数
- `tariff`: 电价与补贴参数
- `cost`: 投资与运维成本参数
- `tax`: 增值税与附加税参数
- `finance`: 折现率与目标 IRR
- `monthly_records`: 历史月度运营数据

对应字段清单见 [docs/input_spec.md](/Users/lihongyang/VSCodeProjects/solar-tariff-roller/docs/input_spec.md)。

## Web 页面

本项目已经提供一个简单 Web 表单用于目标 IRR 反算。

推荐启动命令：

```bash
PYTHONPATH=src uvicorn solar_tariff_roller.api.app:create_app --factory --host 127.0.0.1 --port 9000
```

启动后可访问：

- `http://127.0.0.1:9000/`
- `http://127.0.0.1:9000/docs`
