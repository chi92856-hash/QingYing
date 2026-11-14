"""Independent per-run budgets; only committed new files consume a slot."""


def parse_limits(photo_limit=200,video_limit=20):
    result={}
    for kind,label,value in [('image','照片',photo_limit),('video','视频',video_limit)]:
        try:
            text=str(value).strip()
            if not text.isdecimal():raise ValueError
            number=int(text)
            if number<1:raise ValueError
        except (ValueError,TypeError,OverflowError):
            raise ValueError(label+'上限请输入大于 0 的整数。') from None
        result[kind]=number
    return result


class DownloadBudget:
    def __init__(self,photo_limit=200,video_limit=20,active=('image','video')):
        self.limits=parse_limits(photo_limit,video_limit)
        self.counts={'image':0,'video':0}
        self.active=set(active)

    def remaining(self,kind):
        return max(0,self.limits[kind]-self.counts[kind]) if kind in self.active else 0

    def full(self):return all(self.remaining(kind)==0 for kind in self.active)

    def record(self,kind,count):
        if count<1 or count>self.remaining(kind):raise ValueError('本次文件数量超过该类剩余名额。')
        self.counts[kind]+=count

    def summary(self):
        return f'照片 {self.counts["image"]}/{self.limits["image"]} 张 · 视频 {self.counts["video"]}/{self.limits["video"]} 条'


def parse_item_limit(value):
    text=str(value).strip()
    if not text.isdecimal() or int(text)<1:
        raise ValueError('扫描下载数量请输入大于 0 的整数。')
    return int(text)


class TotalBudget:
    def __init__(self,limit,active):
        self.limit=parse_item_limit(limit)
        self.active=set(active)
        self.counts={'image':0,'video':0}

    def remaining(self,kind):
        return max(0,self.limit-sum(self.counts.values())) if kind in self.active else 0

    def full(self):return sum(self.counts.values())>=self.limit

    def record(self,kind,count):
        if count<1 or count>self.remaining(kind):raise ValueError('超过本次剩余保存数量。')
        self.counts[kind]+=count

    def summary(self):
        return f'已保存 {sum(self.counts.values())}/{self.limit} 项 · 照片 {self.counts["image"]} 张 · 视频 {self.counts["video"]} 条'
