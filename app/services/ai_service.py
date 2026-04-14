from __future__ import annotations

from dataclasses import dataclass

from ..settings import settings

try:
    from openai import APITimeoutError, APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError
except ImportError:  # pragma: no cover - handled at runtime when dependency is absent
    APITimeoutError = APIConnectionError = APIStatusError = AuthenticationError = RateLimitError = None
    OpenAI = None

FEATURE_EXAM_PLAN = 'exam_plan'
FEATURE_TASK_BREAKDOWN = 'task_breakdown'
FEATURE_TIME_ESTIMATE = 'time_estimate'
FEATURE_ASSISTANT_CHAT = 'assistant_chat'


class AIServiceError(Exception):
    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class AIConfigurationError(AIServiceError):
    pass


@dataclass(frozen=True)
class AIResult:
    title: str
    text: str


class AIService:
    def __init__(self):
        self._api_key = settings.openai_api_key
        self._model = settings.openai_model
        self._timeout = settings.openai_timeout_seconds

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def answer_study_request(self, *, request_text: str) -> AIResult:
        return AIResult(
            title='Ответ AI Assistant',
            text=self._generate(
                system_prompt=(
                    'Ты AI Assistant для учебного приложения Student Assistant. '
                    'Пользователь пишет свободный учебный запрос, а ты должен понять намерение и дать практический результат. '
                    'Главные сценарии: план подготовки к экзамену, разбиение задачи на шаги, оценка времени подготовки. '
                    'Если запрос похож на один из этих сценариев, используй соответствующую структуру. '
                    'Если запрос комбинированный, объедини ответ в один понятный план. '
                    'Пиши на русском языке, без воды, без пустой мотивации, без канцелярита. '
                    'Всегда делай ответ удобным для чтения: короткий заголовок, затем блоки или списки. '
                    'Если данных не хватает, в начале кратко укажи допущения и всё равно помоги.'
                ),
                user_prompt=(
                    'Подготовь полезный ответ на запрос студента.\n'
                    'Правила:\n'
                    '- если это просьба составить подготовку к экзамену, верни блоки "Цель", "План", "Темы", "Повторение", "Советы";\n'
                    '- если это просьба разбить задачу, верни блоки "Что сделать", "Шаги", "Сроки", "Риски", "Советы";\n'
                    '- если это просьба оценить время, верни блоки "Оценка", "Диапазон часов", "Факторы", "Как ускорить", "Как улучшить результат";\n'
                    '- если запрос неидеальный, выбери наиболее подходящий сценарий сам.\n\n'
                    f'Запрос пользователя: {request_text}'
                ),
            ),
        )

    def _generate(self, *, system_prompt: str, user_prompt: str) -> str:
        if OpenAI is None:
            raise AIConfigurationError(
                'Пакет openai не установлен. Выполните установку зависимостей из requirements.txt.'
            )
        if not self._api_key:
            raise AIConfigurationError(
                'OPENAI_API_KEY не настроен. Добавьте ключ в .env, чтобы использовать AI Assistant.'
            )

        client = OpenAI(api_key=self._api_key, timeout=self._timeout)

        try:
            response = client.responses.create(
                model=self._model,
                input=[
                    {
                        'role': 'system',
                        'content': [{'type': 'input_text', 'text': system_prompt}],
                    },
                    {
                        'role': 'user',
                        'content': [{'type': 'input_text', 'text': user_prompt}],
                    },
                ],
                max_output_tokens=1400,
            )
        except AuthenticationError as exc:
            raise AIConfigurationError(
                'Не удалось авторизоваться в OpenAI API. Проверьте корректность OPENAI_API_KEY.'
            ) from exc
        except RateLimitError as exc:
            raise AIServiceError(
                'Превышен лимит запросов OpenAI API. Подождите немного и повторите попытку.'
            ) from exc
        except APIConnectionError as exc:
            raise AIServiceError(
                'Не удалось связаться с OpenAI API. Проверьте подключение и повторите попытку.'
            ) from exc
        except APITimeoutError as exc:
            raise AIServiceError(
                'OpenAI API не ответил вовремя. Попробуйте повторить запрос чуть позже.'
            ) from exc
        except APIStatusError as exc:
            if exc.status_code == 429:
                raise AIServiceError(
                    'OpenAI API временно ограничил запросы. Попробуйте немного позже.'
                ) from exc
            raise AIServiceError(
                f'OpenAI API вернул ошибку {exc.status_code}. Попробуйте повторить запрос позже.'
            ) from exc
        except Exception as exc:
            raise AIServiceError(
                'Не удалось получить ответ от AI Assistant. Попробуйте повторить запрос позже.'
            ) from exc

        output_text = (response.output_text or '').strip()
        if not output_text:
            raise AIServiceError('AI Assistant получил пустой ответ. Попробуйте уточнить запрос.')

        return output_text


ai_service = AIService()
