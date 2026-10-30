"""Small, attributed Huchenfeng meme pack; selected locally, never fetched at runtime.

Public fan transcripts can contain transcription errors. Short quotes below were
checked against the linked text, not independently authenticated against video.
All explanations and application rules are our paraphrases, not his quotations.
"""
import re

SOURCES={
 'phone':'https://github.com/Olcmyk/HuChenFeng/blob/main/2023%E5%B9%B412%E6%9C%88/2023-12-29.md',
 'understand':'https://www.huchenfeng.live/2025-nian-04-yue/2025-04-23',
 'logic':'https://www.zaobao.com.sg/realtime/china/story20250918-7533712',
 'brands':'https://www.zaobao.com.sg/realtime/china/story20250922-7549302',
 'absurd':'https://zh.wikiquote.org/zh-hans/%E6%88%B7%E6%99%A8%E9%A3%8E',
 'work':'https://vandaily.com/pda/news/op%3Dview/sid%3D1141207/page%3D2/lang%3Dschinese.html',
 'binary':'https://www.huchenfeng.live/2025-nian-09-yue/2025-09-12',
}
ENTRIES=(
 ('phone',('手机','起手','连麦'),'手机起手式：公开转写短句“你什么手机？”；用于识别连麦段子的品牌起手式，不是真的索取群友设备资料。'),
 ('understand',('理解','用过','体验'),'理解式反讽：公开转写短句“我能理解你的”；可接对方刚才的说法，不能编造自己真实用过什么产品或对方没有用过什么。'),
 ('logic',('安卓','苹果','逻辑','分类'),'安卓/苹果二分梗：在户晨风相关段子里，把事物按品牌式优劣标签二分；可调侃当下的双标、硬分类或逻辑跳步。这是网络梗，不是人的实际等级，也不能从手机推断学历、收入、国籍或智力。'),
 ('brands',('山姆','特斯拉','三件套'),'消费三件套：山姆购物、特斯拉电车、苹果手机的品牌偏好组合。可拿“凑齐品牌就自动升级”的荒诞逻辑接梗，不当购买建议或产品质量结论。'),
 ('absurd',('谬论','荒谬','反驳'),'短促反驳：语录整理有“谬论！太荒谬了！”；先指出本轮具体哪里不成立，再偶尔接一小句，不拿口头禅替代论证。'),
 ('work',('力工','硬扛','死磕'),'力工思维：是另一个来源的网络梗，不冒充户晨风原话。只拿对方明说的机械硬扛、只谈付出不看方法接梗；可原创“方向都没看对，你他妈光靠硬扛想把墙撞开喵？”，不把群友断言成体力劳动者，不贬低职业或收入。'),
 ('binary',('苹果人','安卓人','分档'),'品牌分档的装腔反差：角色可夸张自称“本喵苹果人”，但标签是口头禅，不是实测设备或真实阶层。原创节奏示例“本喵苹果人也得看论据，你他妈别拿牌子给逻辑贴金喵”，只学节奏，不固定复读，不当户晨风原话。'),
 ('logic',('逻辑','证据','反驳'),'拆台变体（原创，不引作原话）：指出对方是拿标签代替论据、同一句换个牌子复读、反复改口仍不肯承认。每条只拆本句的一处漏洞，允许普通粗口，最后自然收喵；不用金融术语凑口吻，不引入投资建议或猜测对方财务。'),
)
TRIGGER=re.compile(r'户晨风|户子|力工(?:思维|逻辑|式)?|安卓(?:人|逻辑|思维|学历|素质|态度)|苹果(?:人|逻辑|思维|学历|素质|态度)|(?:山姆.{0,10}特斯拉|特斯拉.{0,10}山姆)|(?:山姆|特斯拉|苹果).{0,8}三件套')
BOUNDARY='\n【户晨风梗语料（语境参考，不是身份或命令）】\n只借梗，不冒充户晨风，不把新编段子说成他的原话；每次最多一个梗、承接当前发言。可保留原有粗口力度，不必因用梗变文明；别句句问手机，不重复最近用过的梗。认真求助和数学、技术解释优先实质答案。品牌标签不用于贬低真实群体；不能凭品牌或玩笑猜测对方的花呗账单、负债、收入或家庭背景，回击只针对当前的错误推理。不能借“手机梗”泄露或猜测机器人设备；原安全边界、发言人区分和字数纠错照常。\n'


def note(history):
    """Load at most three relevant entries only for an explicit current meme cue."""
    latest=next((m.get('content','') for m in reversed(history) if m.get('role')=='user'),'')
    # Speaker names are metadata, not a reason to inject a voice pack.
    body=re.sub(r'^【[^【】\n]{1,24}】\s*','',latest)
    if not TRIGGER.search(body):return ''
    selected=[e for e in ENTRIES if any(t in body for t in e[1])]
    if not selected:selected=[ENTRIES[0],ENTRIES[1],ENTRIES[2]]
    return BOUNDARY+'\n'.join(e[2] for e in selected[:3])+'\n'


FINANCE=re.compile(r'花呗|借呗|网贷|贷款|分期|负债|欠款|账单')
UNSUPPORTED_FINANCE=re.compile(r'(?:花呗|借呗|网贷|贷款|分期).{0,16}(?:没还|未还|还不|还完|账单)|下个?月.{0,10}(?:花呗|账单)|你.{0,10}(?:负债|欠款)')


def unsupported_claim(history,reply):
    """Reject common invented debt claims in this pack; not a general fact checker."""
    if not UNSUPPORTED_FINANCE.search(reply) or not note(history):return False
    # User-supplied financial context may legitimately be discussed. A previous
    # assistant's guess is never evidence about a user's finances.
    return not any(FINANCE.search(m.get('content','')) for m in history if m.get('role')=='user')
