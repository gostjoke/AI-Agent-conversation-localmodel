"""
Agent tools registry.
Agent 工具註冊表 —— 用 @tool 裝飾器新增你自己的工具（例如 SAP、SQL Server 查詢）。

Each tool = a Python function + JSON schema that Ollama sends to the model.
每個工具 = 一個 Python 函式 + 給模型看的 JSON schema。
"""

import ast
import datetime as dt
import operator
import os
from pathlib import Path
from typing import Callable

# Sandbox folder the agent may read/write. 代理只能讀寫此資料夾（沙盒）。
WORKSPACE = Path(os.getenv("AGENT_WORKSPACE", Path(__file__).parent / "workspace")).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)

MAX_READ_CHARS = 20_000

TOOLS: dict[str, dict] = {}  # name -> {"fn", "schema", "label"}


def tool(name: str, description: str, params: dict | None = None,
         required: list[str] | None = None, label: str | None = None):
    """Register a function as an agent tool. 將函式註冊為 agent 工具。"""
    def deco(fn: Callable):
        TOOLS[name] = {
            "fn": fn,
            "label": label or name,
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": params or {},
                        "required": required or [],
                    },
                },
            },
        }
        return fn
    return deco


def _safe_path(rel: str) -> Path:
    """Resolve path inside WORKSPACE only. 防止路徑跳出沙盒。"""
    p = (WORKSPACE / (rel or ".")).resolve()
    if p != WORKSPACE and WORKSPACE not in p.parents:
        raise ValueError(f"Path outside workspace is not allowed: {rel}")
    return p


# ── Built-in tools 內建工具 ───────────────────────────────────────────────────

@tool("get_current_time", "Get the current local date and time.", label="目前時間 Time")
def get_current_time() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)")


_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        if isinstance(node.op, ast.Pow) and abs(_eval(node.right)) > 100:
            raise ValueError("Exponent too large")
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("Unsupported expression")


@tool("calculator", "Evaluate an arithmetic expression exactly, e.g. '(1200*0.85)/3'.",
      {"expression": {"type": "string", "description": "Arithmetic expression"}},
      ["expression"], label="計算機 Calculator")
def calculator(expression: str) -> str:
    return str(_eval(ast.parse(expression, mode="eval").body))


@tool("list_files", "List files in the agent workspace folder (or a sub-folder).",
      {"path": {"type": "string", "description": "Relative sub-folder, default '.'"}},
      label="列出檔案 List files")
def list_files(path: str = ".") -> str:
    p = _safe_path(path)
    if not p.is_dir():
        return f"Not a folder: {path}"
    rows = [f"{'[D]' if c.is_dir() else '[F]'} {c.relative_to(WORKSPACE)}"
            + ("" if c.is_dir() else f"  ({c.stat().st_size} bytes)")
            for c in sorted(p.iterdir())]
    return "\n".join(rows) or "(empty)"


@tool("read_file", "Read a UTF-8 text file (txt, csv, md, json, py, sql...) from the workspace.",
      {"path": {"type": "string", "description": "Relative file path"}},
      ["path"], label="讀取檔案 Read file")
def read_file(path: str) -> str:
    p = _safe_path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_READ_CHARS:
        return text[:MAX_READ_CHARS] + f"\n...[truncated, total {len(text)} chars]"
    return text


@tool("write_file", "Create or overwrite a UTF-8 text file in the workspace.",
      {"path": {"type": "string", "description": "Relative file path"},
       "content": {"type": "string", "description": "Full file content"}},
      ["path", "content"], label="寫入檔案 Write file")
def write_file(path: str, content: str) -> str:
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Saved {p.relative_to(WORKSPACE)} ({len(content)} chars)"


# ── Example: add your own tool 範例：新增自訂工具 ─────────────────────────────
# @tool("query_po", "Look up a purchase order in SQL Server by PO number.",
#       {"po": {"type": "string"}}, ["po"], label="查詢 PO")
# def query_po(po: str) -> str:
#     import pyodbc
#     ...  # return rows as text / CSV; 回傳文字或 CSV 給模型


def run_tool(name: str, args: dict | None) -> str:
    """Execute a tool and always return text. 執行工具，錯誤也以文字回傳給模型。"""
    t = TOOLS.get(name)
    if not t:
        return f"Error: unknown tool '{name}'"
    try:
        return str(t["fn"](**(args or {})))
    except Exception as e:  # model sees the error and can retry 讓模型看到錯誤並重試
        return f"Error: {type(e).__name__}: {e}"


def tool_schemas(names: list[str] | None = None) -> list[dict]:
    return [t["schema"] for n, t in TOOLS.items() if names is None or n in names]


def tool_list() -> list[dict]:
    return [{"name": n, "label": t["label"],
             "description": t["schema"]["function"]["description"]} for n, t in TOOLS.items()]
