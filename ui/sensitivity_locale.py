"""Localized descriptions for actual low-threshold input controls."""
SENSITIVITY_TRANSLATIONS = {
    "en": {
        "scroll.hscroll_threshold_title": "Horizontal wheel shortcut sensitivity",
        "scroll.hscroll_threshold": "Trigger amount (lower is more sensitive)",
        "scroll.hscroll_repeat": "Shortcut repeat interval",
        "scroll.hscroll_threshold_help": "1% = 0.01 logical scroll step; repeat interval can be set from 1 ms. Lower values act on actual event accumulation and repeat filtering. Integer-only device reports cannot gain sub-step precision. Very short intervals may repeat actions unexpectedly. Volume keeps its separate 60 ms guard.",
        "mouse.low_threshold_help": "Threshold starts at 1 px and changes actual recognition distance, including low-distance tracking and return gates. Very low values can turn button-press jitter into swipes. Existing distance settings are kept.",
        "ring.low_threshold_help": "Minimum hold setting: 1 ms. Very low values may open the ring on ordinary clicks; Windows scheduling does not guarantee exact millisecond timing.",
    },
    "zh_CN": {
        "scroll.hscroll_threshold_title": "横向滚轮快捷键灵敏度",
        "scroll.hscroll_threshold": "触发量（越低越灵敏）",
        "scroll.hscroll_repeat": "快捷键重复触发间隔",
        "scroll.hscroll_threshold_help": "1%＝0.01 个逻辑滚动单位，重复间隔可从 1 ms 调节；实际改变事件累积量和重复过滤。只能上报整数刻度的设备无法凭空增加刻度精度。间隔过短可能连续误触发，音量保留独立的 60 ms 防抖。",
        "mouse.low_threshold_help": "最低 1 px，实际改变识别距离，同时降低小距离时的跟踪、回程门槛。过低可能把按下按钮时的抖动识别成手势；保留现有距离设置。",
        "ring.low_threshold_help": "按住时间最低可设 1 ms，过低可能普通点击就弹出动作环；Windows 调度不能保证精确到每个毫秒。",
    },
    "zh_TW": {
        "scroll.hscroll_threshold_title": "橫向滾輪快捷鍵靈敏度",
        "scroll.hscroll_threshold": "觸發量（越低越靈敏）",
        "scroll.hscroll_repeat": "快捷鍵重複觸發間隔",
        "scroll.hscroll_threshold_help": "1%＝0.01 個邏輯滾動單位，重複間隔可從 1 ms 調整；實際改變事件累積量與重複過濾。只能回報整數刻度的裝置無法憑空增加刻度精度。間隔過短可能連續誤觸發，音量保留獨立的 60 ms 防抖。",
        "mouse.low_threshold_help": "最低 1 px，實際改變辨識距離，同時降低小距離時的追蹤、回程門檻。過低可能把按下按鈕時的抖動辨識成手勢；保留現有距離設定。",
        "ring.low_threshold_help": "按住時間最低可設 1 ms，過低可能普通點擊就彈出動作環；Windows 排程不能保證精確到每個毫秒。",
    },
}
