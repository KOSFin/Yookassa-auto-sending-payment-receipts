import json
import re
from typing import Any


VARIABLE_PATTERN = re.compile(r'\{\{\s*([a-zA-Z0-9_\.]+)\s*\}\}')


def get_nested(payload: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = payload
    for part in path.split('.'):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def build_context(payload: dict[str, Any], store: Any) -> dict[str, Any]:
    payment_id = get_nested(payload, store.payment_id_path, '')
    amount = get_nested(payload, store.amount_path, 0)
    customer_name = get_nested(payload, store.customer_name_path, '')
    return {
        'payment_id': payment_id,
        'amount': amount,
        'customer_name': customer_name,
        'event': payload.get('event', ''),
        'payload': payload,
    }


def render_template(source: str, context: dict[str, Any]) -> str:
    def replace_var(match: re.Match[str]) -> str:
        key = match.group(1)
        value = context
        for part in key.split('.'):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return ''
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return VARIABLE_PATTERN.sub(replace_var, source)
