"""Retry empty required final content without replacing first-attempt scores."""


def required_content_result(chat, messages, salt, check, **extra):
    first = chat(messages, salt, **extra)
    message = first['message']
    retry = None
    if not (message.get('content') or '').strip() and not message.get('tool_calls'):
        # Generate again with the same completed history; never execute tools
        # again, append the empty answer, or expand the output allowance.
        retry = chat(messages, salt, **extra)
    return dict(correct=bool(check(first)), retried_empty_final=retry is not None,
                retry_correct=bool(check(retry)) if retry is not None else None,
                retry_empty_final=not (retry['message'].get('content') or '').strip()
                if retry is not None else None)
