"""Windows UI Automation adapter. Intentionally no coordinate-click fallback."""
import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
import time

import uiautomation as auto
from comtypes import COMError
from .composer import composer_text

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short


def title(hwnd):
    buffer = ctypes.create_unicode_buffer(1024)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


@dataclass
class Selector:
    control_type: str
    name: str
    automation_id: str

    @classmethod
    def capture(cls, control):
        value = cls(control.ControlTypeName, control.Name, control.AutomationId)
        if not value.name and not value.automation_id:
            raise RuntimeError("У элемента нет доступного имени или ID.")
        return value

    def matches(self, control):
        return (control.ControlTypeName == self.control_type
                and (control.AutomationId == self.automation_id if self.automation_id
                     else control.Name == self.name))


class WindowsAdapter:
    def __init__(self, selectors=None):
        self.selectors = {key: Selector(**value) for key, value in (selectors or {}).items()}
        self.hwnd = None
        self.window_title = ""
        self.tab = None
        self.tab_id = None
        self._controls = []
        self._scanned_at = 0
        self._role_controls = {}

    @staticmethod
    def browser_tab(control):
        """Page tabs (e.g. Chat / Work) aren't browser conversation tabs."""
        parent = control.GetParentControl()
        for _ in range(40):
            if parent is None or parent.ControlTypeName == "WindowControl":
                return True
            if parent.ControlTypeName == "DocumentControl":
                return False
            parent = parent.GetParentControl()
        return False

    def controls(self, fresh=False):
        if fresh or time.monotonic() - self._scanned_at > .35:
            root = auto.ControlFromHandle(self.hwnd)
            stack = [(root, 0)]
            result = []
            deadline = time.monotonic() + 3
            while stack:
                control, depth = stack.pop()
                if len(result) > 4000 or time.monotonic() > deadline:
                    raise RuntimeError("Поиск элементов занял слишком много времени. Открой чат в отдельном окне.")
                try:
                    result.append(control)
                    if depth < 30:
                        stack.extend((child, depth + 1) for child in control.GetChildren())
                except COMError:
                    continue
            self._controls = result
            self._scanned_at = time.monotonic()
        return self._controls

    def bind_window(self, hwnd):
        name = title(hwnd)
        if not any(token in name.casefold() for token in ("chatgpt", "codex")):
            raise RuntimeError("Выбери окно с ChatGPT или Codex в заголовке.")
        if self.hwnd is not None and self.hwnd != hwnd:
            self.selectors.clear()
        self.hwnd, self.window_title = hwnd, name
        self.tab = self.tab_id = None
        self._role_controls.clear()
        candidates = []
        for control in self.controls(fresh=True):
            try:
                if (control.ControlTypeName == "TabItemControl" and self.browser_tab(control)
                        and control.GetSelectionItemPattern().IsSelected):
                    candidates.append(control)
            except (COMError, LookupError):
                continue
        if len(candidates) == 1:
            self.tab = candidates[0]
            self.tab_id = self.tab.GetRuntimeId()
        return name

    def available_windows(self):
        result = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def collect(hwnd, unused):
            name = title(hwnd)
            if user32.IsWindowVisible(hwnd) and any(t in name.casefold() for t in ("chatgpt", "codex")) and not any(t in name.casefold() for t in ("hey gpt", "computer use", "cursor overlay", "using your computer")):
                result.append((hwnd, name))
            return True
        user32.EnumWindows(callback_type(collect), 0)
        return result

    def discover(self):
        """Known accessible names, never positional guesses."""
        self.validate(require_foreground=False)
        aliases = {
            "composer": ("Спросить ChatGPT", "Ask anything", "Message ChatGPT", "Сообщение ChatGPT"),
            "microphone": ("Диктовать", "Dictate"),
        }
        for role, names in aliases.items():
            matches = [c for c in self.controls() if c.ControlTypeName == ("EditControl" if role == "composer" else "ButtonControl") and c.Name in names and not c.IsOffscreen]
            if len(matches) == 1:
                self.selectors[role] = Selector.capture(matches[0])
        mic = self.selectors.get("microphone")
        if mic and mic.name in ("Диктовать", "Dictate"):
            ru = mic.name == "Диктовать"
            self.selectors.setdefault("finish", Selector("ButtonControl", "Остановить диктовку" if ru else "Stop dictation", ""))
            self.selectors.setdefault("send", Selector("ButtonControl", "Отправить" if ru else "Send prompt", ""))
        self.find("composer")
        self.find("microphone")

    def prepare_target(self):
        if not self.hwnd or not user32.IsWindow(self.hwnd):
            raise RuntimeError("Выбранное окно закрыто. Выбери чат в настройках.")
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, 9)
        if user32.GetForegroundWindow() != self.hwnd:
            user32.SetForegroundWindow(self.hwnd)
            # Windows may prevent activation while another app owns input.
            # Report this instead of changing system policy or clicking elsewhere.
            if user32.GetForegroundWindow() != self.hwnd:
                raise RuntimeError("Windows не разрешила активировать чат. Один раз нажми на его окно и повтори команду.")
        if self.tab is not None:
            if self.tab.GetRuntimeId() != self.tab_id:
                raise RuntimeError("Выбранная вкладка закрыта. Выбери чат заново.")
            selection = self.tab.GetSelectionItemPattern()
            if not selection.IsSelected:
                selection.Select()
                time.sleep(.1)
        self._scanned_at = 0
        self.validate()

    def capture_at_cursor(self, role):
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            raise RuntimeError("Не удалось определить положение курсора.")
        hwnd = user32.GetAncestor(user32.WindowFromPoint(point), 2)
        name = title(hwnd)
        if not any(token in name.casefold() for token in ("chatgpt", "codex")):
            raise RuntimeError("Выбери окно с ChatGPT или Codex в заголовке.")
        if role != "window" and self.hwnd and hwnd != self.hwnd:
            raise RuntimeError("Выбирай элементы в одном окне. Для смены окна начни с шага 1.")
        if role == "window":
            return self.bind_window(hwnd)
        if not self.hwnd:
            raise RuntimeError("Сначала выбери окно чата.")
        control = auto.ControlFromPoint(point.x, point.y)
        for _ in range(12):
            if control is None:
                break
            if role == "composer":
                if control.ControlTypeName == "EditControl":
                    break
            elif control.ControlTypeName == "ButtonControl":
                break
            control = control.GetParentControl()
        if control is None:
            raise RuntimeError("Под курсором не найден доступный элемент.")
        expected = "EditControl" if role == "composer" else "ButtonControl"
        if control.ControlTypeName != expected:
            raise RuntimeError("Выбери поле сообщения." if role == "composer" else "Выбери кнопку.")
        selected = Selector.capture(control)
        previous = self.selectors.get(role)
        self.selectors[role] = selected
        # Prove the selector is unambiguous now; later it is resolved again.
        try:
            self.find(role, require_foreground=False)
        except Exception:
            if previous is None:
                self.selectors.pop(role, None)
            else:
                self.selectors[role] = previous
            raise
        return self.selectors[role].name or self.selectors[role].automation_id

    def validate(self, *, require_foreground=True):
        if not self.hwnd or not user32.IsWindow(self.hwnd):
            raise RuntimeError("Сначала выбери окно чата.")
        if require_foreground and user32.GetForegroundWindow() != self.hwnd:
            raise RuntimeError("Вернись в выбранное окно чата; затем сбрось цикл.")
        if self.tab is not None:
            if self.tab.GetRuntimeId() != self.tab_id or not self.tab.GetSelectionItemPattern().IsSelected:
                raise RuntimeError("Открыта другая вкладка. Повтори голосовую команду, чтобы вернуться в выбранный чат.")
            self.window_title = title(self.hwnd)
        elif title(self.hwnd) != self.window_title:
            raise RuntimeError("Заголовок окна или вкладка изменились. Выбери нужное окно заново.")

    def find(self, role, *, optional=False, require_foreground=False):
        self.validate(require_foreground=require_foreground)
        if role not in self.selectors:
            raise RuntimeError("Сначала настрой элемент: " + role)
        cached = self._role_controls.get(role)
        if cached is not None:
            try:
                if self.selectors[role].matches(cached) and not cached.IsOffscreen:
                    return cached
            except COMError:
                pass
            self._role_controls.pop(role, None)
        matches = []
        for control in self.controls():
            try:
                if self.selectors[role].matches(control) and not control.IsOffscreen:
                    matches.append(control)
                    if len(matches) > 1:
                        raise RuntimeError("Найдено несколько одинаковых элементов: " + role + ". Повтори настройку.")
            except COMError:
                continue
        if not matches:
            if optional:
                return None
            raise RuntimeError("Элемент сейчас не виден: " + role)
        self._role_controls[role] = matches[0]
        return matches[0]

    def click(self, role):
        # Re-check uniqueness for writes; the direct-control cache is read-only.
        self._role_controls.pop(role, None)
        control = self.find(role)
        if not control.IsEnabled:
            raise RuntimeError("Элемент недоступен: " + role)
        self.validate()
        # Invoke the accessible button; never guess screen coordinates.
        control.GetInvokePattern().Invoke()
        self._scanned_at = 0

    def read_text(self):
        control = self.find("composer")
        try:
            raw = control.GetValuePattern().Value
        except Exception:
            raw = control.GetTextPattern().DocumentRange.GetText(-1)
        placeholder = self.selectors["composer"].name
        if raw.strip("\r\n \t\u200b\ufeff") == placeholder.strip():
            return composer_text(raw, placeholder, self.find("send", optional=True) is not None)
        return raw

    def replace_text(self, expected, replacement):
        if self.read_text() != expected:
            raise RuntimeError("Текст изменился во время удаления команды. Проверь черновик.")
        self._role_controls.pop("composer", None)
        control = self.find("composer")
        self.validate()
        try:
            control.GetValuePattern().SetValue(replacement)
        except (COMError, LookupError):
            control.SetFocus()
            self.validate()
            if auto.GetFocusedControl().GetRuntimeId() != control.GetRuntimeId():
                raise RuntimeError("Не удалось установить фокус в поле сообщения.")
            auto.SendKeys("{Ctrl}a", waitTime=0)
            # Literal characters: braces in the dictated message aren't shortcuts.
            for char in replacement:
                self.validate()
                if auto.GetFocusedControl().GetRuntimeId() != control.GetRuntimeId():
                    raise RuntimeError("Фокус изменился при очистке команды. Проверь черновик.")
                units = char.encode("utf-16-le")
                for offset in range(0, len(units), 2):
                    if auto.SendUnicodeChar(chr(int.from_bytes(units[offset:offset + 2], "little"))) != 2:
                        raise RuntimeError("Windows заблокировала ввод. Проверь черновик.")
        self._scanned_at = 0

    def response_status(self):
        self.validate(require_foreground=False)
        busy_names = {"Остановить генерацию", "Остановить ответ", "Stop generating", "Stop streaming", "Stop response"}
        copy_names = {"Копировать", "Скопировать", "Copy", "Copy response"}
        buttons = [c for c in self.controls() if c.ControlTypeName == "ButtonControl"]
        return (any(c.Name in busy_names and not c.IsOffscreen for c in buttons),
                sum(c.Name in copy_names for c in buttons))

    def recording_visible(self):
        return self.find("finish", optional=True) is not None

    def send_enabled(self):
        control = self.find("send", optional=True)
        return control is not None and control.IsEnabled

    def export(self):
        return {key: asdict(selector) for key, selector in self.selectors.items()}


def emergency_pressed():
    # Ctrl + Alt + P, checked even if this application's GUI is not focused.
    return all(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x11, 0x12, 0x50))
