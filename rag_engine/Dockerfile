FROM python:3.12-slim

WORKDIR /app

# 先装 CPU 版 torch：锁版本，不锁版本时 pip 会挑主 PyPI 更高的普通版 torch，
# 经依赖拉 CUDA 全家桶（镜像膨胀 2-3GB）。走 PyTorch 官方 CPU 索引（正规 PEP503 源）。
# 依赖（filelock/sympy 等）从清华 PyPI 解析，故加 --extra-index-url
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 120 --retries 5 torch==2.6.0+cpu \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir --timeout 60 --retries 5 -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 再复制代码
COPY . .

# 不缓冲 stdout：否则 print 会被攒在缓冲区里，Docker 日志中 print 与 uvicorn
# 日志的先后顺序会错乱（uvicorn 的启动日志走 stderr、即时输出，访问日志才走 stdout）
ENV PYTHONUNBUFFERED=1

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
