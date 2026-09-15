"""Bounded retries and schema/semantic validation for all model requests."""
import json, os, time
import httpx
from threading import BoundedSemaphore
_slots=BoundedSemaphore(5)
from pydantic import ValidationError

def request_json(prompt, payload, schema, *, model=None, validate=None, thinking=None, deadline_seconds=None, max_tokens=8000):
    from urllib.parse import urlparse
    extras={'thinking':{'type':thinking}} if thinking and urlparse(os.environ.get('LLM_BASE_URL','')).hostname=='api.deepseek.com' else {}
    messages=[{'role':'system','content':prompt+'\n只返回JSON，严格遵守：'+json.dumps(schema.model_json_schema(),ensure_ascii=False)}, {'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
    deadline=time.monotonic()+deadline_seconds if deadline_seconds else None
    for attempt in range(3):
        try:
            remaining=max(0,deadline-time.monotonic()) if deadline else None
            acquired=_slots.acquire(timeout=remaining) if remaining is not None else _slots.acquire()
            if not acquired:raise TimeoutError('Model queue deadline exceeded')
            try:
                body={'model':model or os.environ['LLM_MODEL'],'messages':messages,'response_format':{'type':'json_object'},'max_tokens':max_tokens,**extras}
                url=os.environ['LLM_BASE_URL'].rstrip('/')+'/chat/completions'
                headers={'Authorization':'Bearer '+os.environ['LLM_API_KEY']}
                if deadline:
                    import asyncio
                    async def bounded_request():
                        async with httpx.AsyncClient(timeout=45) as client:
                            return await client.post(url,headers=headers,json=body)
                    async def bounded():
                        return await asyncio.wait_for(bounded_request(),timeout=max(0,deadline-time.monotonic()))
                    r=asyncio.run(bounded())
                else:
                    with httpx.Client(timeout=90) as client:r=client.post(url,headers=headers,json=body)
                r.raise_for_status()
                result=schema.model_validate_json(r.json()['choices'][0]['message']['content'])
                if validate:validate(result)
                return result
            finally:_slots.release()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (408,429,500,502,503,504) or attempt==2: raise
        except (httpx.TransportError, ValidationError, ValueError, KeyError, IndexError):
            if attempt==2: raise
            if len(messages)==2:
                messages.append({'role':'user','content':'上次输出未通过格式或证据校验。请重新生成，严格遵守字段结构，只引用输入中存在的证据，未知信息明确标注。'})
        time.sleep(0.5*(2**attempt))
