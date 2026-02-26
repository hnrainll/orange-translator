.PHONY: install reinstall uninstall dev help log ot

help:
	@echo "常用命令："
	@echo "  make install    安装 ot 命令到系统（~/.local/bin）"
	@echo "  make dev        以可编辑模式安装（修改代码立即生效）"
	@echo "  make reinstall  重新安装（更新依赖或版本后使用）"
	@echo "  make uninstall  卸载 ot 命令"
	@echo "  make log        查看持久化翻译日志（~/.local/share/orange-translator/）"

install:
	uv tool install .

dev:
	uv tool install . --editable

reinstall:
	uv tool install . --reinstall

uninstall:
	uv tool uninstall orange-translator

log:
	@tail -f ~/.local/share/orange-translator/ot-translate.log

# 本地开发运行：通过 uv run 执行，.env 中的配置自动生效
# 用法：make ot test.epub
#       make ot test.epub --from en --to ja
ot:
	uv run ot $(filter-out ot,$(MAKECMDGOALS))

# 捕获 make ot 后面的参数（如文件名、选项），避免 Make 报"无此目标"错误
%:
	@:
