# Capy Free Models

Capy 免费模型的 AnyFlows `provider.lifecycle` 插件。插件会读取 Capy 模型目录，只返回标记为广告免费且价格为零的模型。

当前默认模型为 `deepseek/deepseek-v4.1-flash-ads` 和 `zai/glm-5.3-flash-ads`。

## 安装

在仓库根目录打包：

```sh
python scripts/package_plugin.py
```

生成与 `manifest.json` 版本号一致的 `.afplugin`，可在 AnyFlows 的插件管理中上传安装。若同名包已存在，添加 `--force` 覆盖。

## 配置

插件配置的 `sessions` 填入一个或多个 Capy Cookie：

```json
{
  "sessions": [
    "__client=第一条Cookie",
    "__client=第二条Cookie"
  ]
}
```

在 Provider 绑定中启用 `sessionEnabled`，设置 `upstreamResponseMode` 为 `non_streaming`，并配置三个 endpoint：

| ID | 地址 | 方法 | 路径 | WebSocket |
| --- | --- | --- | --- | --- |
| `clerk` | `https://clerk.capy.ai` | GET、POST | `/v1/client` | 否 |
| `capy-api` | `https://api.capy.ai` | GET、POST | `/app` | 否 |
| `capy-realtime` | `wss://realtime-production.cloud.capy.ai` | — | `/realtime` | 是 |

每次请求轮换 Cookie。认证、免费模型或 device 根线程不可用时会尝试其他 Cookie。模型回答通过已有 device 根线程派生的 side thread 获取。

插件默认在回答后删除 side thread。设置 `deleteAfter` 为 `false` 可保留它。

## 测试

需要 Python 3.10 或更新版本。运行：

```sh
python -m unittest discover -s tests -v
```

## 许可

插件代码采用 MIT 许可。随包的 `anyflows_plugin.py` 按 AGPL-3.0 许可提供，来源见 `NOTICE.md`。
