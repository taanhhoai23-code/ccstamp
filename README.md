# CC·STAMP

CC·STAMP 是运行在 BTCC（Bitcoin Classic）链上的铭文 / NFT 铸造与钱包系统。

## 功能

- 批量生成 CC·STAMP seed
- 铸造交易写入 `OP_RETURN`
- 每枚铭文用 `vout=1` 的 0.001 BTCC dust 作为载体
- 支持网页铸造台
- 支持浏览器钱包查看、转移铭文
- 支持链上索引器同步归属

## 链上格式

铸造交易：

```json
{"p":"cc-stamp","op":"gen","s":"CC-STAMP-00001-0"}
```

转移交易：

```json
{"p":"cc-stamp","op":"xfer","s":"CC-STAMP-00001-0"}
```

约定：

- `vout[0]`：`OP_RETURN` 铭文数据
- `vout[1]`：0.001 BTCC dust，当前持有人地址

## 目录

- `app.py`：铸造台后端
- `wallet_api.py`：钱包 API
- `wallet_indexer.py`：链上索引器
- `generator.py`：seed / 图像生成逻辑
- `templates/`：页面模板
- `static/`：前端资源

## 不包含内容

开源仓库不包含：

- 数据库文件
- 钱包文件
- 私钥 / 助记词
- `.env`
- 生产日志
- 备份文件
- 运行时审计文件

## 许可证

MIT
