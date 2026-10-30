FROM python:3.12-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive DISPLAY=:99 QT_QPA_PLATFORM=xcb QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 QT_ACCESSIBILITY=1 NO_AT_BRIDGE=0 LANG=C.UTF-8 HOME=/home/wechat PYTHONPATH=/usr/lib/python3/dist-packages
RUN sed -i "s|http://deb.debian.org/debian-security|https://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|https://mirrors.aliyun.com/debian|g" /etc/apt/sources.list.d/debian.sources && apt-get update && apt-get install -y --no-install-recommends \
    xvfb openbox dbus-x11 at-spi2-core python3-gi gir1.2-atspi-2.0 python3-pil python3-xlib \
    x11vnc novnc websockify xclip x11-utils fonts-noto-cjk procps \
    libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-render-util0 libxcb-xinerama0 libxcb-shape0 libxcb-cursor0 \
    libxcb-xkb1 libxcb-randr0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libgbm1 libasound2 libpulse0 libpango-1.0-0 libcairo2 \
    libatspi2.0-0 libgtk-3-0 libatomic1 libgl1 libegl1 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 1000 --create-home wechat && mkdir /app && chown wechat:wechat /app
COPY entrypoint.sh /app/entrypoint.sh
COPY transport.py /app/transport.py
USER wechat
WORKDIR /app
ENTRYPOINT ["dbus-run-session","--","bash","/app/entrypoint.sh"]
