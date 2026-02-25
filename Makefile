.PHONY: install reinstall uninstall dev help

help:
	@echo "常用命令："
	@echo "  make install    安装 ot 命令到系统（~/.local/bin）"
	@echo "  make dev        以可编辑模式安装（修改代码立即生效）"
	@echo "  make reinstall  重新安装（更新依赖或版本后使用）"
	@echo "  make uninstall  卸载 ot 命令"

install:
	uv tool install .

dev:
	uv tool install . --editable

reinstall:
	uv tool install . --reinstall

uninstall:
	uv tool uninstall orange-translator
