# CC·STAMP Protocol

CC·STAMP 是 BTCC 链上的轻量铭文格式。

每枚 STAMP 由一个 seed 标识，链上交易用 `OP_RETURN` 写入协议数据，并用一枚 dust UTXO 作为持有凭证。

## 铸造

`vout[0]` 写入：

```json
{"p":"cc-stamp","op":"gen","s":"CC-STAMP-00001-0"}
```

`vout[1]` 是载体输出，发送到接收地址。

## 转移

`vout[0]` 写入：

```json
{"p":"cc-stamp","op":"xfer","s":"CC-STAMP-00001-0"}
```

新的 `vout[1]` 是转移后的载体输出。

## 归属

索引器按区块顺序读取 CC·STAMP 交易，并以最新有效载体输出作为当前持有人。
