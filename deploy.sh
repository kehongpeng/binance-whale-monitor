#!/bin/bash
# 服务器自动部署脚本
# Usage: ./deploy.sh [update|restart|status|logs]

APP_DIR="/opt/binance-whale-monitor"
APP_NAME="whale-monitor"
PYTHON="${APP_DIR}/venv/bin/python3"
PIP="${APP_DIR}/venv/bin/pip3"

cd "$APP_DIR" || exit 1

case "$1" in
    update)
        echo "🔄 更新代码..."
        git pull origin $(git rev-parse --abbrev-ref HEAD)

        echo "📦 安装依赖..."
        $PIP install -r requirements.txt -q

        echo "🔄 重启服务..."
        ./deploy.sh restart
        ;;

    restart)
        echo "🛑 停止旧服务..."
        pkill -f "realtime_server.py" 2>/dev/null || true
        sleep 2

        echo "🚀 启动实时监控服务..."
        nohup $PYTHON realtime_server.py > server.log 2>&1 &

        echo "⏳ 等待服务启动..."
        sleep 3

        if curl -s http://localhost:8888 > /dev/null; then
            echo "✅ 服务启动成功! http://localhost:8888"
        else
            echo "❌ 服务启动失败，查看日志: tail -f server.log"
        fi
        ;;

    status)
        echo "📊 服务状态:"
        pgrep -f "realtime_server.py" > /dev/null && echo "✅ 实时监控: 运行中" || echo "❌ 实时监控: 已停止"

        echo ""
        echo "🌐 端口监听:"
        netstat -tlnp 2>/dev/null | grep -E '8888|python' || ss -tlnp | grep -E '8888|python'
        ;;

    logs)
        echo "📜 实时日志 (Ctrl+C退出):"
        tail -f server.log
        ;;

    *)
        echo "币安期货监控系统 - 部署脚本"
        echo ""
        echo "Usage:"
        echo "  ./deploy.sh update    - 更新代码并重启"
        echo "  ./deploy.sh restart   - 重启服务"
        echo "  ./deploy.sh status    - 查看状态"
        echo "  ./deploy.sh logs      - 查看日志"
        ;;
esac
