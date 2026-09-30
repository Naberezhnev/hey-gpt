"""Read one assistant bubble through accessibility, never the whole window."""
COPY_NAMES = {"Копировать", "Скопировать", "Copy", "Copy response", "Копировать ответ", "Скопировать ответ", "Copy answer"}
MESSAGE_COPY_NAMES = COPY_NAMES - {"Копировать", "Скопировать", "Copy"}
ASSISTANT_LABELS = {"chatgpt сказал:", "chatgpt said:", "chatgpt:", "codex сказал:", "codex said:"}
USER_LABELS = {"вы сказали:", "you said:", "user:", "ваше сообщение:"}
SKIP_TYPES = {"ButtonControl", "EditControl", "MenuControl", "ToolBarControl", "StatusBarControl"}


def assistant_heading(control):
    return control.ControlTypeName == "TextControl" and control.Name.strip().casefold() in ASSISTANT_LABELS


def same_node(first, second):
    try:
        return first.GetRuntimeId() == second.GetRuntimeId()
    except AttributeError:
        return first is second


def subtree(root, limit=700):
    stack = [(root, 0)]
    nodes = []
    while stack:
        node, depth = stack.pop()
        nodes.append(node)
        if len(nodes) > limit or depth > 25:
            raise ValueError("Ответ слишком большой для чтения через доступность.")
        if node.ControlTypeName not in ("EditControl", "MenuControl"):
            stack.extend((child, depth + 1) for child in reversed(node.GetChildren()))
    return nodes


def bubble_text(root, nodes):
    if root.ControlTypeName in SKIP_TYPES:
        return ""
    parts = []
    def collect(node):
        if node.ControlTypeName in SKIP_TYPES:
            return
        children = node.GetChildren()
        if node.ControlTypeName == "TextControl" and isinstance(node.Name, str) and node.Name.strip():
            parts.append(node.Name.strip())
            return
        for child in children:
            collect(child)
    collect(root)
    if parts:
        return "\n".join(parts)
    try:
        text = root.GetTextPattern().DocumentRange.GetText(-1)
        if isinstance(text, str):
            lines = [line for line in text.splitlines() if line.strip() and line.strip() not in COPY_NAMES]
            return "\n".join(lines)
    except Exception:
        pass
    return ""


def latest_response(controls):
    headings = [control for control in controls if assistant_heading(control)]
    if headings:
        heading = headings[-1]
        parent = heading.GetParentControl()
        while parent is not None and assistant_heading(parent):
            heading, parent = parent, parent.GetParentControl()
        if parent is None or parent.ControlTypeName == "WindowControl":
            raise ValueError("Не удалось определить границы последнего ответа.")
        started = False
        parts = []
        for child in parent.GetChildren():
            if same_node(child, heading):
                started = True
                continue
            if not started:
                continue
            if child.ControlTypeName == "TextControl" and child.Name.strip().casefold() in ASSISTANT_LABELS | USER_LABELS:
                break
            if child.ControlTypeName == "TextControl" and getattr(child, "AriaRole", "") == "description":
                continue
            nodes = subtree(child)
            if any(node.ControlTypeName == "EditControl" for node in nodes):
                break
            text = bubble_text(child, nodes).strip()
            if text:
                parts.append(text)
        if parts:
            return "\n".join(parts)
        raise ValueError("Последний ответ пока пуст или недоступен.")
    explicit = any(node.ControlTypeName == "ButtonControl" and node.Name in MESSAGE_COPY_NAMES for node in controls)
    anchors = MESSAGE_COPY_NAMES if explicit else COPY_NAMES
    for control in reversed(controls):
        if control.ControlTypeName != "ButtonControl" or control.Name not in anchors:
            continue
        parent = control.GetParentControl()
        for _ in range(8):
            if parent is None or parent.ControlTypeName in ("DocumentControl", "WindowControl"):
                break
            nodes = subtree(parent)
            copies = [node for node in nodes if node.ControlTypeName == "ButtonControl" and node.Name in anchors]
            user_labels = tuple(USER_LABELS)
            if (len(copies) != 1 or any(node.ControlTypeName == "EditControl" for node in nodes)
                    or any(isinstance(node.Name, str) and node.Name.casefold().startswith(user_labels) for node in nodes)):
                break
            text = bubble_text(parent, nodes).strip()
            if text:
                return text
            parent = parent.GetParentControl()
        # Never fall back to an older reply when the newest one is inaccessible.
        break
    raise ValueError("Текст ответа недоступен. Открой последний ответ и проверь чтение в настройках.")
