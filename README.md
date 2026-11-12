# Siril DSO Skill

一个用于 **Siril 深空图像处理**的 Agent Skill：检查素材和校准条件，协助从零建立暗场/校准库，完成校准、配准、叠加及后期，并保存可复查的处理总结。

**先检查，再问清楚，再处理。** 它不会假定你有暗场库、使用某台相机、拥有Photoshop或安装了某款付费插件。支持彩色/单色、制冷/非制冷、多夜、多滤镜以及双窄带星云＋独立RGB星点的分支决策。

这是一套给支持 `SKILL.md` 的本地AI助手使用的工作规范，附带可选Siril桥接工具；不是独立图像处理软件，也不是一键固定参数脚本。

## 安装与开始

技能文件夹是 [`siril-deep-sky/`](siril-deep-sky/)。可以让具备技能安装功能的助手从本仓库安装这个文件夹。

Codex手动安装示例：将整个 `siril-deep-sky` 目录复制到项目的 `.agents/skills/` 或用户的 `~/.agents/skills/` 下，形成 `…/siril-deep-sky/SKILL.md`。若你的客户端使用另一技能目录，以其实际配置为准；避免安装多个同名副本。发现方式和当前目录约定见 [OpenAI官方技能文档](https://learn.chatgpt.com/docs/build-skills)。

在支持显式技能调用的Codex中可这样开始：

```text
使用 $siril-deep-sky 处理这次深空素材。
工作目录是……，目标是……。先检查素材和校准条件。
```

也可以说：

- “我没有暗场库，帮我按这次照片的参数建一套。”
- “这些是双窄带星云和无滤镜星点，分别处理后合成。”
- “控制我已经打开的Siril，让我逐步看到结果。”
- “我已在PS修完无星图，打开星点合成界面。”

助手应先读取能够获得的文件信息，再询问关键缺项。可以直接说“不知道”“不能补拍”“保留全幅”“没有PS”；技能会选择适用路线，不要求你猜设置。

## 处理与输出

- 检查文件类型、设备、曝光、滤镜、温度、几何和处理状态，避免把缩略图当曝光或重复校准。
- 查找用户提供的校准库；没有库时给出实际参数、目录、张数起点、拍摄时间和验收步骤。
- 校准场缺失或失效时解释替代路线，关键不确定性先问，保留原始素材。
- 根据真实质量筛片、配准与叠加，输出线性32位FITS。
- 后期按目标和偏好进行；PS是可选往返，窄带风格和星点强度可交互调整。
- 每次叠加后生成报告：各类场的张数/曝光/拍摄日期、master制作时间、逐步参数和结果/预览；后期继续追加。

默认每个素材组的中间文件放其 `process/`；最终FITS、TIFF和报告只放对应目标文件夹，不在整晚拍摄总目录制造重复副本。用户另有约定时遵循其明确选择。

## 可选：连接已打开的Siril

需要助手能够访问运行Siril的同一台机器和文件系统。仅有网页聊天、远端容器或本仓库本身，不会自动获得桌面控制能力。

桥接从Siril的Python环境启动，依赖该版本的 `sirilpy` 接口；客户端只用Python标准库。实际Windows/Siril 1.4.5工作流已有使用经验；脚本有POSIX文件锁实现，但macOS/Linux GUI连接尚未实机验证。旧版本缺少Python接口时可选择CLI或手工操作。

首次连接、JSON计划、超时恢复和信任边界见 [GUI连接说明](siril-deep-sky/references/gui-control.md)。桥接是本机命令通道，包含脚本执行能力，不是安全沙箱。安装前应阅读脚本，并只在受信任的工作目录运行。

## 内容导航

| 内容 | 位置 |
|---|---|
| 技能入口 | [SKILL.md](siril-deep-sky/SKILL.md) |
| 信息不清楚时怎样询问 | [intake.md](siril-deep-sky/references/intake.md) |
| 有/无各类校准场的路线 | [calibration.md](siril-deep-sky/references/calibration.md) |
| 从零建库与维护 | [calibration-library.md](siril-deep-sky/references/calibration-library.md) |
| 主场、校准、配准与筛片 | [manual-workflow.md](siril-deep-sky/references/manual-workflow.md) |
| 多夜、多滤镜、双窄带＋RGB | [multigroup.md](siril-deep-sky/references/multigroup.md) |
| 后期、去星、PS与合成 | [postprocessing.md](siril-deep-sky/references/postprocessing.md) |
| 报告要求 | [reporting.md](siril-deep-sky/references/reporting.md) |

## 验证与边界

在仓库根目录运行：

```text
python -m unittest discover -s tests -v
python tests/validate_package.py
```

自动测试验证文件通道、重复实例锁、旧session拒绝、失败停止和超时续等，不依赖Siril，也不证明图像处理质量。真实GUI、第三方模型和图像结果仍需现场检查。[场景检查清单](tests/scenarios.md)用于行为审阅，不冒充已在所有设备上执行的测试。

仓库不包含原始天文图像、个人拍摄记录、设备库、模型权重或第三方处理脚本。Siril及GraXpert、StarNet、VeraLux等可选工具需按各自官方渠道和许可证安装；这里不重新授权它们。

本仓库沿用已有的 [Apache-2.0许可证](LICENSE)。官方操作依据见各参考文件；具体命令先与本机版本的 `help` 核对。
