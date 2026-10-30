"""Bounded display variants. Safety decisions retain their internal sentinel.

No untrusted request text, classification reason or model call enters this path.
The job key makes retries display the same text and keeps send idempotency intact.
"""
import hashlib

SHARP=(
    '这茬不接，换个话题喵。',
    '哼，这个不聊喵。',
    '这事本喵不接，聊点别的。',
    '别搁这试探了，这个不答喵。',
    '这题本喵跳过，换一个喵。',
)
CALM=(
    '这个话题我不展开喵。',
    '这部分不便回答，可以换个话题喵。',
    '这个请求我不能帮忙喵。',
    '这项我不回应了喵。',
)


def display_refusal(job_key,calm=False):
    variants=CALM if calm else SHARP
    index=int.from_bytes(hashlib.sha256(str(job_key).encode()).digest()[:8],'big')%len(variants)
    return variants[index]


def is_refusal(text):
    return text=='唐完了' or text in SHARP or text in CALM
