"""Small stdio MCP interface. stdout contains protocol messages only."""
import json
import sys
import threading

from .codex_service import rpc, wait_for_voice
from .model_setup import ensure_model


def schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required),
            "additionalProperties": False}


SESSION = {"type": "string", "description": "session_id этой задачи, предоставленный SessionStart. Не выдумывай ID."}
TOOLS = [
    {"name": "voice_status", "description": "Проверить состояние Hey GPT и доступные голоса Windows; микрофон не включает.", "inputSchema": schema(), "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "voice_prepare_models", "description": "Один раз скачать английскую и русскую модели Vosk (~85 МБ). Микрофон не открывает.", "inputSchema": schema(), "annotations": {"readOnlyHint": False, "openWorldHint": True}},
    {"name": "voice_enable", "description": "По явному запросу пользователя включить локальный микрофон для одной текущей задачи и сохранить автозапуск. Другую задачу не выбирает самостоятельно.", "inputSchema": schema({"session_id": SESSION}, ("session_id",)), "annotations": {"readOnlyHint": False, "openWorldHint": False}},
    {"name": "voice_disable", "description": "Остановить озвучку, закрыть микрофон, отменить диктовку и отключить автозапуск прослушивания.", "inputSchema": schema(), "annotations": {"readOnlyHint": False, "openWorldHint": False}},
    {"name": "voice_repeat", "description": "Повторить последнюю озвучку из памяти без повторного выполнения задачи.", "inputSchema": schema(), "annotations": {"readOnlyHint": False, "openWorldHint": False}},
    {"name": "voice_settings", "description": "Настроить автозапуск, сводку, язык локальной диктовки и установленный голос Windows.", "inputSchema": schema({"autostart": {"type": "boolean"}, "summary": {"type": "boolean"}, "language": {"type": "string", "enum": ["ru", "en"]}, "voice_id": {"type": "string"}}), "annotations": {"readOnlyHint": False, "openWorldHint": False}},
    {"name": "voice_wait", "description": "По просьбе пользователя ждать голосовой ввод Hi GPT → диктовка → Stop GPT в текущей задаче, до 50 секунд. Вернуть дословное распознанное сообщение. Основное ожидание до 58 минут выполняет обработчик Stop. После таймаута не перезапускать ожидание без запроса пользователя.", "inputSchema": schema({"session_id": SESSION, "seconds": {"type": "integer", "minimum": 1, "maximum": 50}}, ("session_id",)), "annotations": {"readOnlyHint": False, "openWorldHint": False}},
]


class MCPServer:
    def __init__(self, output=None, call=rpc, wait=wait_for_voice):
        self.output = output or (lambda value: print(json.dumps(value, ensure_ascii=False), flush=True))
        self.call, self.wait = call, wait
        self.lock = threading.Lock()
        self.pending = {}

    def emit(self, value):
        with self.lock:
            self.output(value)

    def dispatch(self, message):
        identity = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        if method == "notifications/cancelled":
            event = self.pending.get(params.get("requestId"))
            if event:
                event.set()
            return
        if identity is None:
            return
        if method == "initialize":
            offered = params.get("protocolVersion")
            versions = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
            result = {"protocolVersion": offered if offered in versions else versions[-1],
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "hey-gpt-codex", "version": "0.1.0-beta.3"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            cancel = threading.Event()
            self.pending[identity] = cancel
            threading.Thread(target=self.tool, args=(identity, params, cancel), daemon=True).start()
            return
        else:
            self.emit({"jsonrpc": "2.0", "id": identity, "error": {"code": -32601, "message": "Method not found"}})
            return
        self.emit({"jsonrpc": "2.0", "id": identity, "result": result})

    def tool(self, identity, params, cancel):
        try:
            name, args = params.get("name"), params.get("arguments") or {}
            spec = next((tool for tool in TOOLS if tool["name"] == name), None)
            if spec is None:
                raise ValueError("Unknown tool")
            allowed = spec["inputSchema"]["properties"]
            if not isinstance(args, dict) or any(key not in allowed for key in args):
                raise ValueError("Invalid tool arguments")
            if any(key not in args for key in spec["inputSchema"]["required"]):
                raise ValueError("Missing required argument")
            if name == "voice_prepare_models":
                ensure_model(progress=lambda value: None)
                ensure_model(progress=lambda value: None, language="ru")
                value = {"models_ready": True}
            elif name == "voice_wait":
                seconds = args.get("seconds", 40)
                if type(seconds) is not int or not 1 <= seconds <= 50:
                    raise ValueError("seconds must be 1..50")
                value = self.wait(args["session_id"], timeout=seconds, cancelled=cancel.is_set)
            else:
                value = self.call({"action": name.removeprefix("voice_"), **args})
            result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "isError": False}
        except Exception as exc:
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        finally:
            self.pending.pop(identity, None)
        if not cancel.is_set():
            self.emit({"jsonrpc": "2.0", "id": identity, "result": result})

    def run(self):
        for line in sys.stdin:
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("Expected object")
                self.dispatch(value)
            except (ValueError, TypeError, AttributeError):
                self.emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
        for event in self.pending.values():
            event.set()
