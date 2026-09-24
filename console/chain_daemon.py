#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务状态刷新守护进程：独立于 Web 控制台运行，不隐式提交链式任务。

用法（后台运行，关掉终端也不停）：
    nohup python3 chain_daemon.py > chain_daemon.log 2>&1 &

逻辑：每 20 秒刷新规范化任务状态。链式任务的前置版本和是否继续生成
必须由用户在控制台明确选择。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import batch_console as bc


def main():
    server = bc.DEFAULT_SERVER
    print(f"[daemon] 启动，服务器 {server}，每 20 秒检查一次", flush=True)
    while True:
        try:
            state = bc.load_state()
            store = bc.get_task_store()
            store.migrate_legacy_tasks(state.get("tasks", []), state.get("server") or server)
            active = store.list_attempts(statuses=["queued", "running", "cancel_requested"])
            if not active:
                print(f"[daemon] {time.strftime('%H:%M:%S')} 无活动任务，持续待命", flush=True)
                time.sleep(20)
                continue
            refreshed = bc.get_task_service().refresh_active_attempts()
            done = sum(1 for item in refreshed if item.get("status") == "succeeded")
            brief = ", ".join(
                "{}:{}".format(item.get("segment_key", "?"), item.get("status")) for item in refreshed[-12:]
            )
            print(
                "[daemon] {} 刷新 {} 项，已完成 {} | {}".format(
                    time.strftime("%H:%M:%S"), len(refreshed), done, brief
                ),
                flush=True,
            )
        except Exception as e:
            print(f"[daemon] 错误：{e}", flush=True)
        time.sleep(20)


if __name__ == "__main__":
    main()
