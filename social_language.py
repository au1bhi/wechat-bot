"""Curated everyday Chinese social-media phrases, with locally selected meanings.

These are shared across platforms. Sources establish usage/meaning, not an
X-wide frequency ranking. Entries are paraphrases, not harvested user posts.
"""
import re
from topic_policy import political_reason

SOURCES={
 'human':'https://www.traeai.com/articles/7ad6272f-6f7f-4cae-b878-3f84505a76d3',
 'reply':'https://txs.youth.cn/xw/202402/t20240225_15095291.htm',
 'work':'https://www.why.com.cn/wx/article/2024/12/02/17331235201373085937.html',
 'food':'https://app-web.chnfund.com/YHHEediting/202407/t20240715_4376188.html',
 'terms':'https://rednotememe.com/memes?sort=popularity',
 'surrender':'https://xyh.univs.cn/a/xyh_xyh_fyhzy/250118/1987904.shtml',
}
# Only terms with non-political everyday meanings are included. Terms with
# mixed provenance were excluded rather than importing a whole scraped feed.
ENTRIES=(
 ('human',('活人感','预制回复','预制评论','预制文案'),'活人感/预制回复：前者是自然、有细节的交流；后者吐槽套模板、没接住话。先回应眼前的具体事，别用总结腔刷屏。'),
 ('reply',('已读乱回','乱回','答非所问'),'已读乱回：故意用不搭边的回答搞笑或回避；只在普通玩笑里识别这个梗，不能拿它敷衍求助或事实题。'),
 ('work',('班味','上班','加班','打工','开会','周一'),'班味：上班带来的疲惫和格式化说话感；日常吐槽点到具体安排，不捏造对方被裁、欠薪或老板身份。'),
 ('work',('偷感','社恐','偷偷'),'偷感：小心翼翼、不想被注意的状态，不是在指控偷窃，也不是医学诊断。'),
 ('work',('硬控','看入迷','刷视频','追番'),'硬控：原是游戏控制效果，日常也指被内容吸引而停不下来；可以用反差接梗，不编造确切时长。'),
 ('food',('电子榨菜','下饭','吃饭','刷剧'),'电子榨菜：吃饭或休息时看的轻松内容，不是真的食物。可吐槽“先挑视频才肯吃饭”的小习惯。'),
 ('food',('电子布洛芬','吉伊','chiikawa','卡皮巴拉'),'电子布洛芬：让人放松的可爱内容/IP，是情绪比喻，不是药物或治疗建议。'),
 ('surrender',('已老实','求放过','认怂','我服了'),'已老实、求放过：轻松认怂或自嘲；对方在收手，接一句就停，别继续追着骂。'),
 ('terms',('那咋了','那又怎样'),'那咋了：随口反问、表示不在意的接话；不能拿它否定认真求助者的困扰。'),
 ('terms',('尊嘟','假嘟'),'尊嘟假嘟：真假询问的谐音玩笑；需要核实时仍给事实，别把谐音当证据。'),
 ('terms',('你人还怪好嘞','人还怪好'),'你人还怪好嘞：语境里可是真心夸，也可是轻微反讽，先看对方具体做了什么。'),
 ('terms',('红温','空大','掉分','连跪','上分'),'游戏红温/空大：上头生气或技能没命中；吐槽本局操作，不攻击疾病、身份或现实生活。'),
)

BOUNDARY='\n【非政治日常社交语料】\n以下是跨平台日常梗的释义，不是网友给你的指令，不冒充具体X用户、不把新编句子归给别人。每轮最多用一个梗，接住当前发言；可以沿用原本的粗口力度，别为了像网友而堆梗。这些日常梗只在日常、游戏、文娱、数码语境使用，不强行套进政治评论；不能引入中国相关政治类比、站队或隐喻。其他国家政治按话题规则正常回答，不因这份日常词典而拒答。设备隐私、事实准确、发言人区分、认真求助和对方收手的分寸照常。\n'


def note(history):
    latest=next((m.get('content','') for m in reversed(history) if m.get('role')=='user'),'')
    body=re.sub(r'^【[^【】\n]{1,24}】\s*','',latest)
    if political_reason(body):return ''
    selected=[e for e in ENTRIES if any(t in body.casefold() for t in e[1])]
    if not selected:return ''
    return BOUNDARY+'\n'.join(e[2] for e in selected[:2])+'\n'
