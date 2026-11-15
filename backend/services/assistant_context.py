"""Provider-valid tool conversations, including interrupted research batches."""

from copy import deepcopy


def paired_messages(messages):
    """Keep complete pairs only; never fabricate a result the model did not see."""
    result = []
    index = 0
    while index < len(messages):
        message = messages[index]
        index += 1
        if message.get('tool_calls'):
            responses = []
            while index < len(messages) and messages[index]['role'] == 'tool':
                responses.append(messages[index])
                index += 1
            by_id = {m['tool_call_id']: m for m in responses}
            calls = [c for c in message['tool_calls'] if c['id'] in by_id]
            if calls:
                result.append({**message, 'tool_calls': calls})
                result.extend(by_id[c['id']] for c in calls)
        elif message['role'] != 'tool':
            result.append(message)
    return deepcopy(result)
