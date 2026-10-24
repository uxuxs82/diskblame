# diskblame

![ci](https://github.com/uxuxs82/diskblame/actions/workflows/ci.yml/badge.svg)

[english](README.md) | [русский](README.ru.md) | [español](README.es.md) | [中文](README.zh-CN.md)

`diskblame` 记录磁盘使用情况的历史，并告诉你发生了什么变化。

`du` 和 `ncdu` 只显示当前状态。`diskblame` 把元数据快照存进 SQLite，所以你可以问：上周以来什么变大了，是哪个目录，为什么这个文件还在。

它从不复制你的文件。

## 为什么不直接用 du？

`du` 和 `ncdu` 回答“现在什么最大”。它们不回答“上周以来什么变大了”，除非你保存完整副本或记住数字。`diskblame` 为每个路径保存少量数字，之后再比较。

它面向存储已经很紧张的场景：台式机或磁盘快满的笔记本。数据库只存元数据，所以 100 GiB 目录的快照通常只有几 MB。

| 工具 | 保存历史 | 解释路径 |
| --- | --- | --- |
| `du`, `ncdu` | 否 | 否 |
| `duc` | 索引当前状态 | 否 |
| `snapdiff` | 比较两棵树 | 否 |
| `diskblame` | 元数据快照 | `diff` 和 `why` |

## 安装

需要 Python 3.11 或更高版本。没有运行时依赖。

```sh
pipx install git+https://github.com/uxuxs82/diskblame.git
```

或者从本地副本安装：

```sh
git clone https://github.com/uxuxs82/diskblame.git
cd diskblame
pip install .
```

## 快速开始

```sh
diskblame snap ~
diskblame snap ~
diskblame diff --since 7d
```

第一个快照是基线。第二个快照让 `diff` 有东西可以比较。

显示最大的目录：

```sh
diskblame top --depth 2
```

显示最大的文件：

```sh
diskblame top --files --limit 30
```

解释一个文件：

```sh
diskblame why ~/storage/shared/DCIM/Camera/IMG_0001.jpg
```

`why` 会显示大小、类型、年龄、git 状态、重复文件、附近文本文件中的引用，以及路径是否像缓存或构建目录。它不会声称文件可以安全删除，只给事实和保守结论。

## 命令

| 命令 | 作用 |
| --- | --- |
| `snap [path]` | 扫描目录并保存快照 |
| `diff` | 比较两个快照，默认比较最后两个 |
| `top` | 显示快照中最大的目录或文件 |
| `why <path>` | 解释文件或目录 |
| `chart` | 显示总大小随时间的变化 |
| `watch` | 目录增长超过限制时告警 |
| `prune` | 删除旧快照 |
| `config` | 显示或创建配置文件 |

常用选项：

```sh
diskblame snap ~ --exclude '*.log' --min-file-size 5MiB
diskblame diff --since 30d --path DCIM --limit 10
diskblame diff --files --limit 50
diskblame why ~/Downloads/archive.zip --no-refs
diskblame chart --days 90
diskblame prune --keep 20 --vacuum
diskblame watch --root ~ --since 7d --max-growth 1GiB --snap --interval 1h
```

大多数命令支持 `--json`，方便脚本使用。

## 工作原理

一个快照保存：

- 每个目录一行，包含总大小、文件数和目录数
- 每个大于等于 `min_file_size` 的文件一行，默认 1 MiB
- 快照元数据：根路径、时间、总大小、文件数、目录数、扫描耗时

目录总计包含所有文件，包括低于阈值的文件。阈值只限制 `top --files`、`diff --files` 和重复检查中保存的单个文件。`diff --files` 显示大小变化，不显示内容变化。

目录总计中硬链接只算一次。除非使用 `--follow-symlinks`，否则跳过符号链接。无法读取的条目会被计数并显示，不会当成零。

数据库默认在 `~/.local/share/diskblame/diskblame.db`。几十万条路径的快照相比完整文件副本很小。

## 配置

默认配置是 `~/.config/diskblame/config.toml`。创建配置：

```sh
diskblame config --init
```

示例：

```toml
[scan]
exclude = [".git", ".hg", ".svn", "__pycache__", ".DS_Store", "lost+found"]
min_file_size = "1MiB"
follow_symlinks = false

[db]
path = "~/.local/share/diskblame/diskblame.db"
```

`--db` 和 `--config` 只覆盖当前命令的路径。

## 限制

- 只存元数据，不存文件内容。不能恢复任何东西。
- 不是备份工具，也不能替代 `du`、`ncdu` 或 `duc`。
- 目录大小取决于文件系统的块分配。稀疏文件显示的大小可能小于表观长度。
- 重复检测先比较已保存文件中相同大小的文件，再做哈希。大文件使用前 1 MiB、后 1 MiB 和文件大小。
- 引用搜索在仓库内使用 `git grep`，在仓库外使用有上限的文本文件扫描。
- `watch` 是前台循环。要长期运行，请放在 tmux 或服务管理器里。

## 参与

欢迎提交 issue 和 pull request。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

MIT
