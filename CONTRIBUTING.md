# 开发

需要 Python 3.10 或更新版本。运行测试和构建插件：

```sh
python -m unittest discover -s tests -v
python scripts/package_plugin.py --force
```

提交前确认 Cookie、Bearer token 和本地配置没有进入 Git。打包文件位于 `dist/`，不提交。
