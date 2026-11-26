"""Fictional longitudinal dialogue. Expectations are evaluation-side only."""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Evidence:
    label: str
    span: str
    active: bool | None = True


@dataclass(frozen=True)
class Turn:
    day: str
    text: str
    evidence: tuple[Evidence, ...] = ()
    no_write: bool = False


@dataclass(frozen=True)
class Case:
    title: str
    history: tuple[Turn, ...]
    query_day: str
    query: str
    expected: tuple[str, ...]
    criteria: tuple[str, ...]


def e(label, span, active=True):
    return Evidence(label, span, active)


CASES = {
    "quality-001": Case(
        "跨年职业困惑：自主时间、收入与真实经历",
        (
            Turn("2023-01-10", "我在青松设计工作室做平面设计。", (e("old_job", "我在青松设计工作室做平面设计", False),)),
            Turn("2023-02-12", "比起头衔，我更看重能够自由安排自己的时间。", (e("value", "我更看重能够自由安排自己的时间"),)),
            Turn("2023-03-01", "今天窗外下雨了。", no_write=True),
            Turn("2023-05-19", "我周末常自己做木雕，做的时候很专注。", (e("hobby", "我周末常自己做木雕，做的时候很专注"),)),
            Turn("2023-07-12", "我有个朋友说他想辞职，并不是我想辞职。", no_write=True),
            Turn("2023-09-22", "我去年尝试接独立设计项目，收入不稳定让我很焦虑。", (e("experience", "我去年尝试接独立设计项目，收入不稳定让我很焦虑"),)),
            Turn("2024-01-04", "我每月必须留出固定的家庭生活费，不能接受突然失去收入。", (e("constraint", "我每月必须留出固定的家庭生活费，不能接受突然失去收入"),)),
            Turn("2024-03-17", "冰箱为什么会结霜？", no_write=True),
            Turn("2024-06-15", "如果收入有保障，我才会考虑全职做独立设计。", (e("conditional", "如果收入有保障，我才会考虑全职做独立设计"),)),
            Turn("2024-08-12", "今天特别烦，不过我只是想吐槽一下。", no_write=True),
            Turn("2025-01-20", "我的工作已经变了：我现在在枫桥学校做设计，不再在青松设计工作室工作。", (e("new_job", "我现在在枫桥学校做设计"),)),
            Turn("2025-02-12", "谢谢，今天先聊到这里。", no_write=True),
        ),
        "2026-01-15",
        "这几年我一直在犹豫要不要换一种工作方式，你能结合我过去说过的事情，帮我看看我究竟在追求什么、应该避免什么吗？",
        ("old_job", "value", "experience", "constraint", "conditional", "new_job"),
        ("区分职业变化而非将历史职业当成现状", "联系自主时间与经济稳定的张力",
         "保留独立设计的前置条件，不将朋友的话算成用户意愿", "提出低风险探索，不替用户决定"),
    ),
    "quality-002": Case(
        "否定、纠正与兴趣变化",
        (
            Turn("2023-04-10", "我最喜欢的运动是跑步。", (e("old_sport", "我最喜欢的运动是跑步", False),)),
            Turn("2023-05-20", "我不喜欢拥挤嘈杂的场所。", (e("noise", "我不喜欢拥挤嘈杂的场所"),)),
            Turn("2023-06-01", "假设我喜欢蹦极，你会推荐什么？这只是一个假设。", no_write=True),
            Turn("2023-07-12", "我一直喜欢自己做纸质星图。", (e("craft", "我一直喜欢自己做纸质星图"),)),
            Turn("2024-01-10", "那次跑步体验很好，不过只是一场活动。", no_write=True),
            Turn("2024-02-02", "我之前说错了：我最喜欢的运动其实是游泳，不是跑步。", (e("new_sport", "我最喜欢的运动其实是游泳，不是跑步"),)),
            Turn("2024-05-04", "我今天想一个人待会儿，明天就没事了。", no_write=True),
            Turn("2024-07-08", "我不是完全排斥社交，只是不喜欢很吵的环境。", (e("qualification", "我不是完全排斥社交，只是不喜欢很吵的环境", None),)),
            Turn("2025-03-12", "我通常周末有半天空闲。", (e("time", "我通常周末有半天空闲"),)),
            Turn("2025-08-09", "如何清洗水杯？", no_write=True),
        ),
        "2026-01-10",
        "周末有点无聊，结合你知道的我的兴趣和限制，给我几个适合的活动吧。",
        ("new_sport", "noise", "craft", "time"),
        ("推荐游泳而非将跑步作为最爱", "不把假设蹦极当事实", "不把不喜欢嘈杂理解为完全排斥社交",
         "考虑半天空闲，不武断定义人格"),
    ),
    "quality-003": Case(
        "密集信息与长期候选容量",
        (
            Turn("2023-01-10",
                 "请记住这些长期事实：我住在虚构的白石镇。我每周二休息。我不会开车。我长期学习陶艺。我需要控制每月娱乐开支。",
                 (e("town", "我住在虚构的白石镇"), e("day", "我每周二休息"),
                  e("transport", "我不会开车"), e("art", "我长期学习陶艺"),
                  e("budget", "我需要控制每月娱乐开支"))),
            Turn("2023-02-10", "我更喜欢独自观察鸟类，不太喜欢团队竞赛。", (e("bird", "我更喜欢独自观察鸟类"),)),
            # 44 distinct explicit synthetic records make old evidence compete with recent material.
            *tuple(Turn(f"2024-03-{i % 28 + 1:02d}" if i < 28 else f"2024-04-{i - 27:02d}",
                        f"请记住：我的虚构图书收藏第{i+1:02d}册的编号是 BOOK-{i+1:02d}。",
                        (e(f"book-{i+1:02d}", f"我的虚构图书收藏第{i+1:02d}册的编号是 BOOK-{i+1:02d}"),))
                   for i in range(44)),
        ),
        "2026-01-10",
        "我想安排一个低成本、不依赖开车、适合我休息日的个人活动，你可以结合以前的兴趣推荐吗？",
        ("day", "transport", "art", "budget", "bird"),
        ("密集首轮五条信息是否完整保留，特别观察三条上限", "老记录是否进入候选而非被大量近期记录挤出",
         "结合休息日、出行和预算约束，不混入图书编号", "未知的现实地点信息不编造"),
    ),
}


def validate_cases(cases=CASES):
    for key, case in cases.items():
        labels = set()
        prior = ""
        for turn in case.history:
            if date.fromisoformat(turn.day).isoformat() != turn.day or turn.day < prior:
                raise ValueError(f"{key}: invalid history chronology")
            prior = turn.day
            if turn.no_write and turn.evidence:
                raise ValueError(f"{key}: contradictory turn expectation")
            for item in turn.evidence:
                if not item.label or item.label in labels or not item.span or item.span not in turn.text:
                    raise ValueError(f"{key}: invalid evidence")
                labels.add(item.label)
        if date.fromisoformat(case.query_day).isoformat() != case.query_day or case.query_day < prior:
            raise ValueError(f"{key}: invalid query date")
        if not set(case.expected) <= labels or len(set(case.expected)) != len(case.expected):
            raise ValueError(f"{key}: unknown or duplicate expected evidence")
    return cases
