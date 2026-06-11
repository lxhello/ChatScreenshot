# ChatExtractor-Screenshot Version 配置文件

CONFIG = {
    # 滚动参数（按屏幕比例动态计算）
    "swipe_duration": 450,           # 滚动动画时长 (ms)
    "swipe_interval": 0.9,           # 两次滚动间隔 (秒)
    "top_swipe_duration": 260,       # 找顶部时的快速滚动时长
    "top_swipe_rounds": 4,           # 每轮找顶部连续滑动次数
    "top_stable_threshold": 2,       # 顶部稳定判定阈值（降低等待次数，减少录屏模式1启动耗时）

    # 截图控制
    "max_screenshots": 0,            # 单次最大截图数（0 表示无限制，直到手动停止或重复边界）
    "duplicate_threshold": 4,        # 连续重复N次自动停止
    "similarity_threshold": 0.985,   # 相似度高于该值视作重复
    "top_detection_threshold": 0.990,# 顶部检测相似度阈值
    "bottom_motion_threshold": 0.040,# 垂直位移低于该比例时，认为页面基本没有继续滚动
    "bottom_motion_threshold_hits": 2,# 连续低位移命中次数，用于确认触底

    # 截图质量
    "screenshot_format": "png",
    "crop_status_bar": True,
    "crop_bottom_bar": True,

    # 输出根目录
    "output_root": "./projects",
}
