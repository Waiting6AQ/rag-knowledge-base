FROM python:3.12-slim

WORKDIR /app

# 先装 CPU 版 torch：锁版本 + -f 指向 CPU 源——
# 阿里云 CPU 源是扁平文件列表（非 PEP503 索引），只能当 find-links 用；
# 不锁版本时 pip 会挑主 PyPI 更高的普通版 torch，经依赖拉 CUDA 全家桶（镜像膨胀 2-3GB）。
# CPU 源最高提供 2.6.0+cpu；依赖（filelock/sympy 等）由 -i 从 PyPI 解析
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 60 --retries 5 torch==2.6.0+cpu -f https://mirrors.aliyun.com/pytorch-wheels/cpu -i https://mirrors.aliyun.com/pypi/simple/ && \
    pip install --no-cache-dir --timeout 60 --retries 5 -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

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
