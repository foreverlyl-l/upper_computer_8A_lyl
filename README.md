# upper_computer_8A_lyl

## 使用已发布的 Docker 镜像

新建 `docker-compose.yml`：

```yaml
name: access-console

x-backend-env: &backend-env
  ENVIRONMENT: development
  DEBUG: "false"
  ENABLE_DOCS: "false"
  DATABASE_URL: sqlite:////data/access_control.db
  SECRET_KEY: change-this-to-a-long-random-secret
  CORS_ORIGINS: '["http://localhost:5500","http://127.0.0.1:5500"]'
  ALLOWED_HOSTS: '["localhost","127.0.0.1","backend"]'
  ADMIN_TOTP_SECRET: JBSWY3DPEHPK3PXP
  ADMIN_TOTP_ISSUER: door
  AUTO_SEED_DEFAULT_USERS: "true"
  SEED_ADMIN_USERNAME: admin
  SEED_ADMIN_PASSWORD: admin-docker-pass-123
  SEED_OPERATOR_USERNAME: operator
  SEED_OPERATOR_PASSWORD: operator-docker-pass-123
  ACCESS_TOKEN_EXPIRE_MINUTES: "30"
  LOGIN_RATE_LIMIT_PER_MINUTE: "8"
  LOGIN_LOCKOUT_SECONDS: "180"

services:
  backend:
    image: ghcr.io/foreverlyl-l/upper_computer_8a_lyl-backend:latest
    restart: unless-stopped
    environment: *backend-env
    volumes:
      - backend_data:/data

  udp-listener:
    image: ghcr.io/foreverlyl-l/upper_computer_8a_lyl-backend:latest
    restart: unless-stopped
    command: ["python", "net_build/udp_packet_listener.py"]
    depends_on:
      - backend
    environment: *backend-env
    volumes:
      - backend_data:/data
    ports:
      - "9000:9000/udp"

  frontend:
    image: ghcr.io/foreverlyl-l/upper_computer_8a_lyl-frontend:latest
    restart: unless-stopped
    depends_on:
      - backend
    ports:
      - "5500:80"

volumes:
  backend_data:
```

启动：

```powershell
docker compose up -d
```

前端页面：

```text
http://localhost:5500
```

停止：

```powershell
docker compose down
```

## 从源码本地构建

在仓库根目录运行：

```powershell
docker compose up -d --build
```

打开：

```text
http://localhost:5500
```

## 默认账号

管理员账号：

```text
用户名：admin
密码：admin-docker-pass-123
```

监视员账号：

```text
用户名：operator
密码：operator-docker-pass-123
```

管理员登录需要动态验证码。默认密钥如下，可通过 Google 身份验证器或其他身份验证器生成动态密码：

```text
JBSWY3DPEHPK3PXP
```
