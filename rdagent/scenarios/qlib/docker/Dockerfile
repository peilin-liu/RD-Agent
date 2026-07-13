# 1. 使用官方 Python 3.11 镜像（底层为 Debian 11 Bullseye）
FROM python:3.11.0

RUN cat /etc/os-release

# 安装编译 QLib 必备的 GCC 编译器和基础工具
RUN apt-get clean && apt-get update && apt-get install -y \
    curl \
    vim \
    git \
    build-essential \
    coreutils \
    && rm -rf /var/lib/apt/lists/*

# 3. 全局配置 Python Pip 为清华大学镜像源（补全完整地址）
# RUN python -m pip config set global.index-url https://tsinghua.edu.cn

RUN mkdir -p /root/.pip
RUN echo "[global]\ntimeout = 15\nindex-url = https://mirrors.aliyun.com/pypi/simple\n" > /root/.pip/pip.conf

RUN pip install uv
# 安装 ARM64 兼容的 PyTorch CPU 版本（清华源秒下）
RUN uv pip install torch torchvision catboost xgboost tables --system

# 4. 克隆 QLib 源码并锁定微软指定稳定版本（修复了原代码中的空格错误，采用国内极速 Gitee 镜像）
RUN git clone https://github.com/microsoft/qlib.git /workspace/qlib
WORKDIR /workspace/qlib
RUN git fetch && git reset 2fb9380b342556ddb50a4b24e4fe8655d548b2b8 --hard

# 编译 QLib 底层 C++ 算子
RUN python -m pip install --upgrade cython
RUN python -m pip install -e .

# 安装基础机器学习模型库
#RUN pip install catboost
#RUN pip install xgboost
#RUN pip install tables
