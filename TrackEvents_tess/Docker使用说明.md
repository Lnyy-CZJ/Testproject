# 埋点测试工具 Docker 使用说明

## 启动服务

在项目目录执行：

```bash
docker compose up -d --build
```

启动后打开：

```text
http://127.0.0.1:8000
```

## 更新 default.log

项目目录下的 `default.log` 会以只读方式挂载到容器中。替换或更新该文件后，重新点击网页中的“开始解析”即可生效，不需要重新构建镜像或重启容器。

## 查看状态与日志

```bash
docker compose ps
docker compose logs -f trackevents
```

## 停止服务

```bash
docker compose down
```

## 修改访问端口

如果宿主机 8000 端口被占用，将 `docker-compose.yml` 中的端口映射改为例如：

```yaml
ports:
  - "18000:8000"
```

然后访问 `http://127.0.0.1:18000`。
