FROM python:3.11-slim

WORKDIR /app

# 安装 curl（用于健康检查）
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# 复制主服务依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制投喂服务依赖
COPY account-feeder/requirements.txt ./account-feeder/
RUN pip install --no-cache-dir -r account-feeder/requirements.txt

# 复制主服务代码
COPY *.py .
COPY templates ./templates
COPY frontend ./frontend

# 复制投喂服务代码
COPY account-feeder/*.py ./account-feeder/
COPY account-feeder/*.html ./account-feeder/

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 8000 8001

# 启动命令（docker-compose 会覆盖此命令）
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 4 & cd account-feeder && python app.py"]
