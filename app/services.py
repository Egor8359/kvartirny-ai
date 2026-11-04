import json
import os
from sqlalchemy import select
from openai import OpenAI
from .database import Fact, Message, Apartment, now
from .prompts import SALES_AGENT_PROMPT, MEMORY_EXTRACTION_PROMPT

LABELS = {
    'budget_max':'Бюджет до, ₽', 'rooms':'Количество комнат (0 — студия)',
    'min_area':'Площадь от, м²', 'preferred_floor':'Желаемый этаж',
    'exclude_first_floor':'Исключить первый этаж', 'finishing':'С отделкой',
    'payment_method':'Оплата', 'delivery_year':'Сдача не позже',
    'other_preferences':'Другие пожелания', 'interested_apartment':'Интересующая квартира',
}

def validate_fact(key, value):
    if key not in LABELS:
        raise ValueError('Неизвестное поле памяти')
    if key in ('exclude_first_floor', 'finishing'):
        good = type(value) is bool
    elif key in ('budget_max', 'min_area'):
        import math
        good = type(value) in (int, float) and math.isfinite(value) and 0 < value <= (1000000000 if key == 'budget_max' else 1000)
    elif key in ('rooms', 'preferred_floor', 'delivery_year'):
        good = type(value) is int and (value in range(4) if key == 'rooms' else value in (2027, 2028) if key == 'delivery_year' else 1 <= value <= 100)
    elif key == 'payment_method':
        good = value in ('mortgage', 'cash') and type(value) is str
    else:
        good = type(value) is str and 0 < len(value.strip()) <= 500
        if key == 'interested_apartment':
            good = good and value in CATALOG_IDS
    if not good:
        raise ValueError('Некорректное значение: ' + LABELS[key])
    return value

CATALOG_IDS = {'A-101','A-406','A-905','B-203','B-705','B-1201','C-804','C-1104','C-301','C-1403','A-1203','B-102'}

def facts_for(db, user_id):
    return {f.fact_key:json.loads(f.fact_value) for f in db.scalars(select(Fact).where(Fact.user_id == user_id))}

def fact_rows(db, user_id):
    return [dict(key=f.fact_key, value=json.loads(f.fact_value), source=f.source,
        source_message_id=f.source_message_id, updated_at=f.updated_at.isoformat())
        for f in db.scalars(select(Fact).where(Fact.user_id == user_id).order_by(Fact.id))]

def upsert_fact(db, uid, key, value, source, message_id=None):
    validate_fact(key, value)
    fact = db.scalar(select(Fact).where(Fact.user_id == uid, Fact.fact_key == key))
    encoded = json.dumps(value, ensure_ascii=False)
    if fact and fact.fact_value == encoded:
        return False
    if fact:
        fact.fact_value, fact.source, fact.source_message_id, fact.updated_at = encoded, source, message_id, now()
    else:
        db.add(Fact(user_id=uid, fact_key=key, fact_value=encoded, source=source, source_message_id=message_id))
    db.flush()
    return True

def validate_changes(raw, message):
    data = json.loads(raw)
    if type(data) is not dict or set(data) != {'changes'} or type(data['changes']) is not list or len(data['changes']) > 10:
        raise ValueError('Неверный формат памяти')
    seen = set()
    for change in data['changes']:
        if type(change) is not dict or set(change) != {'action','key','value','evidence'}:
            raise ValueError('Неверный формат изменения')
        key = change['key']
        if type(key) is not str or key not in LABELS or key in seen:
            raise ValueError('Неизвестный или повторный ключ')
        seen.add(key)
        evidence = change['evidence']
        if type(evidence) is not str or not evidence.strip() or evidence not in message:
            raise ValueError('Нет подтверждения в новом сообщении')
        if change['action'] == 'upsert':
            validate_fact(key, change['value'])
        elif change['action'] != 'delete' or change['value'] is not None:
            raise ValueError('Недопустимое действие')
    return data['changes']

def apply_changes(db, uid, changes, message_id):
    changed = False
    for c in changes:
        if c['action'] == 'upsert':
            changed = upsert_fact(db, uid, c['key'], c['value'], 'chat', message_id) or changed
        else:
            row = db.scalar(select(Fact).where(Fact.user_id == uid, Fact.fact_key == c['key']))
            if row:
                db.delete(row)
                changed = True
    db.flush()
    return changed

def apartment_dict(a):
    return {key:getattr(a,key) for key in ('id','building','rooms','area','floor','total_floors','price','finishing','delivery_year','status')}

def conditions(facts):
    result = {}
    if 'budget_max' in facts: result['budget_max'] = Apartment.price <= facts['budget_max']
    if 'rooms' in facts: result['rooms'] = Apartment.rooms == facts['rooms']
    if 'min_area' in facts: result['min_area'] = Apartment.area >= facts['min_area']
    if 'preferred_floor' in facts: result['preferred_floor'] = Apartment.floor == facts['preferred_floor']
    if facts.get('exclude_first_floor'): result['exclude_first_floor'] = Apartment.floor > 1
    if 'finishing' in facts: result['finishing'] = Apartment.finishing == facts['finishing']
    if 'delivery_year' in facts: result['delivery_year'] = Apartment.delivery_year <= facts['delivery_year']
    if 'interested_apartment' in facts: result['interested_apartment'] = Apartment.id == facts['interested_apartment']
    return result

def select_apartments(db, facts):
    filters = conditions(facts)
    stmt = select(Apartment).where(Apartment.status == 'available', *filters.values()).order_by(Apartment.price)
    matches = [apartment_dict(a) for a in db.scalars(stmt)]
    conflicts, alternatives = [], []
    if not matches:
        # Enumerate violated constraints for each real alternative, including combined conflicts.
        all_rows = list(db.scalars(select(Apartment).where(Apartment.status == 'available').order_by(Apartment.price)))
        for row in all_rows:
            unmet = []
            for key, condition in filters.items():
                if not db.scalar(select(Apartment.id).where(Apartment.id == row.id, condition)):
                    unmet.append(key)
            alternatives.append({'apartment':apartment_dict(row), 'differences':unmet})
        alternatives.sort(key=lambda item:(len(item['differences']), item['apartment']['price']))
        alternatives = alternatives[:3]
        conflicts = sorted({k for item in alternatives for k in item['differences']})
    return dict(matches=matches[:3], conflicts=conflicts, alternatives=alternatives)

def build_context(db, uid, conversation_id):
    # Caller has already checked ownership; enforce it here too.
    from .database import Conversation
    if not db.scalar(select(Conversation.id).where(Conversation.id == conversation_id, Conversation.user_id == uid)):
        raise ValueError('Диалог недоступен')
    rows = list(db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.desc()).limit(12)))
    facts = facts_for(db, uid)
    return dict(facts=facts, history=[{'role':m.role,'content':m.content} for m in reversed(rows)], catalog=select_apartments(db, facts))

class RouterAI:
    def complete(self, prompt, messages):
        key = os.getenv('ROUTERAI_API_KEY', '')
        if not key:
            raise RuntimeError('Не настроен ROUTERAI_API_KEY')
        with OpenAI(api_key=key, base_url=os.getenv('ROUTERAI_BASE_URL','https://routerai.ru/api/v1'), timeout=40, max_retries=2) as client:
            response = client.chat.completions.create(model=os.getenv('ROUTERAI_MODEL','deepseek/deepseek-v3.2'),
                messages=[{'role':'system','content':prompt}, *messages], temperature=0, response_format={'type':'json_object'}, max_tokens=1200)
            return response.choices[0].message.content

    def extract(self, text, facts):
        return self.complete(MEMORY_EXTRACTION_PROMPT, [{'role':'user','content':json.dumps({'new_message':text,'current_facts':facts},ensure_ascii=False)}])

    def respond(self, context):
        return self.complete(SALES_AGENT_PROMPT, [
            {'role':'system','content':'Актуальная память и результаты SQL: ' + json.dumps({'facts':context['facts'], **context['catalog']},ensure_ascii=False)},
            *context['history']])

QUESTIONS = {
    'budget_max':'Какой максимальный бюджет рассматриваете?',
    'rooms':'Сколько комнат вам нужно?', 'min_area':'Какая минимальная площадь вам подойдёт?',
    'preferred_floor':'Есть пожелания к этажу?', 'finishing':'Нужна ли отделка?',
    'delivery_year':'Какой срок сдачи вам подходит?',
    'viewing':'Хотите выбрать квартиру для обсуждения просмотра? Здесь можно обсудить пожелания; заявки не отправляются.',
    'continue':'Продолжим подбор или уточним пожелания?',
}
REASONS = {'budget':('budget_max','в пределах бюджета'), 'rooms':('rooms','нужное число комнат'),
    'finishing':('finishing','подходящая отделка'), 'floor':('preferred_floor','подходящий этаж'),
    'area':('min_area','достаточная площадь'), 'delivery':('delivery_year','подходящий срок сдачи')}

def describe(a):
    rooms = 'Студия' if a['rooms'] == 0 else str(a['rooms']) + '-комнатная'
    price = f"{a['price']:,}".replace(',', ' ')
    return f"{a['id']} · {rooms}, {a['area']:g} м² · {a['floor']}/{a['total_floors']} этаж · {price} ₽ · {'с отделкой' if a['finishing'] else 'без отделки'} · {a['building']}, {a['delivery_year']} г."

def render_answer(raw, context):
    plan = json.loads(raw)
    if type(plan) is not dict or set(plan) != {'apartment_ids','reasons','next_question','intent'}:
        raise ValueError('Неверный план ответа AI')
    ids, reasons, question, intent = (plan[k] for k in ('apartment_ids','reasons','next_question','intent'))
    if type(ids) is not list or len(ids) > 3 or any(type(i) is not str for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Неверные квартиры')
    if type(reasons) is not list or any(type(r) is not str or r not in REASONS for r in reasons):
        raise ValueError('Неверные причины')
    if type(question) is not str or question not in QUESTIONS or intent not in ('selection','privacy','company','financing'):
        raise ValueError('Неверный тип ответа')
    available = {a['id']:a for a in context['catalog']['matches']}
    if any(i not in available for i in ids):
        raise ValueError('AI выбрал квартиру вне SQL-подбора')
    if intent == 'privacy':
        return 'Я работаю только с вашими предпочтениями. Данные других клиентов и изменение прав доступа в чате недоступны. Продолжим подбор для вас?'
    if intent == 'company':
        return '«Северный квартал» — вымышленный девелопер. ЖК «Северный парк» в Тюмени, корпуса A, B и C, условная сдача в 2027–2028 годах. Все данные учебные. Продолжим подбор?'
    if intent == 'financing':
        return 'В каталоге нет подтверждённых ипотечных ставок, скидок или условий оплаты. Могу сохранить способ оплаты как пожелание и подобрать квартиру по бюджету.'
    if context.get('memory_extraction_failed'):
        return 'Не удалось безопасно распознать новые пожелания. Сохранённая память не изменена. Уточните пожелания ещё раз или сохраните их в разделе «Мои данные». После уточнения продолжим подбор.'
    lines = []
    if available:
        ids = ids or list(available)[:3]
        lines.append('По вашим текущим пожеланиям подходят:')
        for aid in ids:
            lines.append(describe(available[aid]))
        verified = [REASONS[r][1] for r in dict.fromkeys(reasons) if REASONS[r][0] in context['facts']]
        if verified:
            lines.append('Почему подходят: ' + ', '.join(verified) + '.')
    else:
        lines.append('Точных совпадений нет. Ближайшие варианты требуют изменить ограничения:')
        for item in context['catalog']['alternatives']:
            lines.append(describe(item['apartment']) + '\nОтличия от пожеланий: ' + ', '.join(LABELS[k] for k in item['differences']) + '.')
        if not context['catalog']['alternatives']:
            lines.append('В каталоге нет доступных квартир.')
        lines.append('Какие требования можно изменить?')
        return '\n\n'.join(lines)
    if question in context['facts']:
        question = 'continue'
    lines.append(QUESTIONS[question])
    return '\n\n'.join(lines)
