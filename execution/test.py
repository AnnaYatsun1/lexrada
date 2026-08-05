import anthropic
import json


client = anthropic.Anthropic(
    api_key="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"
)

contract_text = """
ДОГОВОР № 47 от 12 марта 2025 года

Заказчик: ООО "Альфа Логистик", в лице директора Петрова И.С.
Исполнитель: ФОП Сидоренко О.В.

Предмет договора: разработка корпоративного сайта.

Сумма договора: 180 000 грн (НДС не облагается).
Срок выполнения работ: 60 календарных дней с момента подписания.
Оплата: 50% предоплата, 50% по факту приёмки работ.

Штрафные санкции: за каждый день просрочки исполнитель уплачивает 
0.5% от суммы договора, но не более 10% от общей суммы.

Договор может быть расторгнут в одностороннем порядке при условии 
письменного уведомления за 14 дней.
"""

# response = client.messages.create(
#     model="claude-haiku-4-5",
#     max_tokens=200,
#     messages=[
#         {"role": "user", "content": "Скажи привет"}
#     ]
# )

message = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": f"""
            Проанализируй договор и извлеки следующие поля:
Проанализируй договор и верни JSON:

{{
  "contract_number": "",
  "date": "",
  "client": "",
  "executor": "",
  "subject": "",
  "amount": "",
  "deadline": "",
  "payment_terms": "",
  "penalties": "",
  "termination": ""
}}

{contract_text}
- Номер договора
- Дата
- Стороны (заказчик и исполнитель)
- Предмет
- Сумма
- Срок выполнения
- Условия оплаты
- Штрафные санкции
- Условия расторжения

Текст договора:
# {contract_text}

Верни структурированный список."""
        }
    ]
)
# print(message.content[0].text)

raw = message.content[0].text

try:
    data = json.loads(raw)
    print("OK:", data)
except Exception as e:
    print("Ошибка JSON:", e)
    print(raw)