import tempfile
from pathlib import Path
import unittest
from hey_gpt.briefing import make_briefing, with_voice_instruction, VOICE_INSTRUCTION
from hey_gpt.response import latest_response
from hey_gpt.settings import load_preferences, save_preferences


class BriefingTests(unittest.TestCase):
    def test_gpt_summary_with_two_full_questions_and_choices(self):
        response = "Подробный ответ.\n\n## Голосовая сводка\nЧерновик подготовлен. Отправка ожидает твоего решения.\n\n" \
            "## Вопросы к тебе\n1. От кого отправлять?\n- От меня\n- От компании\n2. Какой язык выбрать?\n- Русский\n- Английский"
        brief = make_briefing(response)
        self.assertTrue(brief.generated_by_gpt)
        self.assertEqual(brief.summary, "Черновик подготовлен. Отправка ожидает твоего решения.")
        self.assertEqual(len(brief.questions), 2)
        self.assertIn("От компании", brief.questions[0])
        self.assertIn("Английский", brief.questions[1])
        self.assertIn("Вопрос 2", brief.spoken)
        self.assertNotIn("Подробный ответ", brief.spoken)

    def test_question_in_body_is_not_lost_when_gpt_omits_question_section(self):
        brief = make_briefing("Какой цвет выбрать?\n- Красный\n- Синий\n\nГолосовая сводка:\nНужно выбрать цвет.")
        self.assertIn("Синий", brief.questions[0])

    def test_no_questions_is_not_announced_as_a_question(self):
        brief = make_briefing("Голосовая сводка\nТесты прошли.\nВопросы к тебе\nНет.")
        self.assertEqual(brief.questions, ())

    def test_fallback_keeps_failure_later_in_response(self):
        brief = make_briefing("Файл создан. Макет готов. Подробности здесь. Проверить отправку не удалось.")
        self.assertFalse(brief.generated_by_gpt)
        self.assertIn("не удалось", brief.summary)
        self.assertTrue(brief.summary.startswith("Краткий фрагмент"))

    def test_code_question_and_url_are_not_read_as_a_request(self):
        brief = make_briefing("Работа закончена.\n```python\nprint('Continue?')\n```\nПодробнее: https://example.com")
        self.assertEqual(brief.questions, ())
        self.assertNotIn("print", brief.spoken)
        self.assertNotIn("https://", brief.spoken)

    def test_empty_response_fails_instead_of_inventing_completion(self):
        with self.assertRaises(ValueError):
            make_briefing(" \n")

    def test_instruction_added_once(self):
        prepared = with_voice_instruction("Ответ на первый вопрос")
        self.assertTrue(prepared.startswith("Ответ на первый вопрос"))
        self.assertEqual(with_voice_instruction(prepared).count(VOICE_INSTRUCTION), 1)

    def test_long_fallback_is_explicitly_a_fragment(self):
        brief = make_briefing("Много подробностей " * 100)
        self.assertLess(len(brief.summary), 700)
        self.assertIn("Полный текст в чате", brief.summary)

    def test_fallback_question_keeps_fragmented_sentence_and_table_choices(self):
        brief = make_briefing("Для продолжения выбери\nязык письма?\n| Русский |\n| Английский |")
        self.assertIn("Для продолжения выбери", brief.questions[0])
        self.assertIn("Английский", brief.questions[0])

    def test_long_fallback_prioritizes_failure_over_intro(self):
        brief = make_briefing("Вступление " * 150 + ". Отправить письмо не удалось.")
        self.assertIn("Отправить письмо не удалось", brief.summary)


class Node:
    def __init__(self, kind="GroupControl", name="", children=()):
        self.ControlTypeName, self.Name = kind, name
        self.children, self.parent = list(children), None
        for child in self.children:
            child.parent = self
    def GetChildren(self):
        return self.children
    def GetParentControl(self):
        return self.parent
    def GetTextPattern(self):
        raise LookupError("unsupported")


def tree(root):
    return [root] + [node for child in root.children for node in tree(child)]


def bubble(text):
    return Node(children=[Node("TextControl", text), Node("ToolBarControl", children=[Node("ButtonControl", "Копировать")])])


class ResponseTests(unittest.TestCase):
    def test_nested_speaker_heading_and_paragraph_descriptions_are_supported(self):
        leaf = Node("TextControl", "ChatGPT сказал:")
        heading = Node("TextControl", "ChatGPT сказал:", [leaf])
        paragraph = Node("TextControl", "Полный ответ с вопросом: какой язык выбрать?")
        paragraph.AriaRole = "description"
        timestamp = Node("TextControl", "16:30")
        timestamp.AriaRole = "description"
        root = Node(children=[heading, Node(children=[paragraph]), timestamp])
        self.assertEqual(latest_response(tree(root)), "Полный ответ с вопросом: какой язык выбрать?")

    def test_flat_accessibility_tree_uses_speaker_boundaries_not_user_copy(self):
        root = Node(children=[Node("TextControl", "Вы сказали:"), Node("TextControl", "Старый вопрос"),
            Node("ButtonControl", "Скопировать сообщение"), Node("TextControl", "ChatGPT сказал:"),
            Node("TextControl", "Старый ответ"), Node("ButtonControl", "Копировать"),
            Node("TextControl", "Вы сказали:"), Node("TextControl", "Новый вопрос"),
            Node("ButtonControl", "Скопировать сообщение"), Node("TextControl", "ChatGPT сказал:"),
            Node("TextControl", "Новый ответ"), Node("ButtonControl", "Копировать"),
            Node("TextControl", "Вы сказали:"), Node("TextControl", "Следующий вопрос")])
        self.assertEqual(latest_response(tree(root)), "Новый ответ")

    def test_latest_empty_heading_does_not_return_older_reply(self):
        root = Node(children=[Node("TextControl", "ChatGPT сказал:"), Node("TextControl", "Старый ответ"),
            Node("TextControl", "ChatGPT сказал:"), Node("StatusBarControl")])
        with self.assertRaises(ValueError):
            latest_response(tree(root))

    def test_latest_assistant_not_following_user_or_draft(self):
        root = Node("DocumentControl", children=[bubble("Старый ответ"), bubble("Новый ответ"),
            Node("TextControl", "Моя следующая реплика"), Node("EditControl", "Черновик")])
        self.assertEqual(latest_response(tree(root)), "Новый ответ")

    def test_never_reads_whole_document_with_one_copy_button(self):
        root = Node("DocumentControl", children=[Node("TextControl", "Чужой текст"), Node("ButtonControl", "Копировать")])
        with self.assertRaises(ValueError):
            latest_response(tree(root))

    def test_toolbar_text_is_not_the_answer(self):
        answer = bubble("Что выбрать?\nРусский или английский")
        answer.children[1].children.append(Node("TextControl", "Оценить ответ"))
        answer.children[1].children[-1].parent = answer.children[1]
        root = Node("DocumentControl", children=[answer])
        self.assertEqual(latest_response(tree(root)), "Что выбрать?\nРусский или английский")

    def test_missing_response_is_reported(self):
        with self.assertRaises(ValueError):
            latest_response([Node("EditControl", "Мой текст")])

    def test_latest_inaccessible_response_cannot_fall_back_to_old_success(self):
        root = Node("DocumentControl", children=[bubble("Старый успешный ответ"), bubble("")])
        with self.assertRaises(ValueError):
            latest_response(tree(root))

    def test_shared_chat_container_with_user_text_is_rejected(self):
        chat = Node(children=[Node("TextControl", "Вы сказали: секрет"), Node("ButtonControl", "Копировать")])
        root = Node("DocumentControl", children=[chat])
        with self.assertRaises(ValueError):
            latest_response(tree(root))


class PreferencesTests(unittest.TestCase):
    def test_round_trip_and_reject_wrong_types(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preferences.json"
            save_preferences(path, {"voice_summary": True, "voice_id": "voice-1"})
            self.assertEqual(load_preferences(path), {"voice_summary": True, "voice_id": "voice-1"})
            path.write_text('{"voice_summary": "yes", "voice_id": 1}', encoding="utf-8")
            self.assertEqual(load_preferences(path), {})
