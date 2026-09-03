FROM python:3.12-slim

WORKDIR /app

# 先装 CPU 版 torch（-f 追加阿里云镜像，-i 走国内 PyPI，搜索和下载全走墙内）
COPY requirements.txt .
RUN pip install torch -f https://mirrors.aliyun.com/pytorch-wheels/cpu -i https://mirrors.aliyun.com/pypi/simple/ && \
    pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 再复制代码
COPY . .

# HuggingFace 模型下载走国内镜像（sentence-transformers 自动读取）
ENV HF_ENDPOINT=https://hf-mirror.com

# 模型缓存目录
ENV HF_HOME=/app/.cache/huggingface

# 关闭 reload（避免容器内 WatchFiles 检测模型下载触发重启死循环）
ENV DISABLE_RELOAD=true

# 暴露端口
EXPOSE 8000

# 启动
CMD ["python", "main.py"]
