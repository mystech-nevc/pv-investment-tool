# -*- coding: utf-8 -*-
"""
services/storage.py
方案存储服务（SQLite 本地数据库）

用途：把已测算的方案（参数快照 + 核心指标）持久化到本地 SQLite，
支持多方案长期积累与横向对比，关闭软件后数据不丢失。
数据库文件位置：<项目根>/data/projects.db，随程序发布，无需额外安装数据库服务。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "projects.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schemes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            project_name TEXT,
            created_at TEXT NOT NULL,
            params_json TEXT NOT NULL,
            metrics_json TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def save_scheme(name: str, params: Dict, metrics: Dict) -> int:
    """
    保存方案，返回记录 id
    params : 完整参数字典
    metrics: 核心指标（IRR/NPV/回收期/初始投资等）
    """
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO schemes (name, project_name, created_at, params_json, metrics_json) VALUES (?,?,?,?,?)",
            (
                name,
                params.get("meta", {}).get("项目名称", ""),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                json.dumps(params, ensure_ascii=False),
                json.dumps(metrics, ensure_ascii=False, default=str),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_schemes() -> List[Dict]:
    """列出全部已保存方案（按创建时间倒序）"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, name, project_name, created_at, params_json, metrics_json FROM schemes ORDER BY id DESC"
        ).fetchall()
        out = []
        for rid, name, project_name, created_at, params_json, metrics_json in rows:
            out.append({
                "id": rid,
                "name": name,
                "project_name": project_name,
                "created_at": created_at,
                "params": json.loads(params_json),
                "metrics": json.loads(metrics_json),
            })
        return out
    finally:
        conn.close()


def delete_scheme(scheme_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM schemes WHERE id = ?", (int(scheme_id),))
        conn.commit()
    finally:
        conn.close()


def clear_schemes() -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM schemes")
        conn.commit()
    finally:
        conn.close()


def export_params_json(params: Dict) -> str:
    """参数模板导出为 JSON 文本"""
    return json.dumps(params, ensure_ascii=False, indent=2)


def import_params_json(text: str) -> Optional[Dict]:
    """
    参数模板导入：解析 JSON 并做结构完整性检查
    返回参数字典；格式不合法时返回 None
    """
    import config
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    for group in ("cost", "finance", "tech", "risk"):
        if group not in data or not isinstance(data[group], dict):
            return None
        # 以默认参数为底，补齐缺失键，避免旧模板缺字段导致崩溃
        merged = dict(config.DEFAULT_PARAMS[group])
        merged.update(data[group])
        data[group] = merged
    if "meta" not in data or not isinstance(data["meta"], dict):
        data["meta"] = dict(config.DEFAULT_PARAMS["meta"])
    return data
