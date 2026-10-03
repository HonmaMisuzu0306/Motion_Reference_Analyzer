"""CV 运动测量阈值集中定义。

所有 magic number 集中在此，避免散落在算法代码中。
"""

# 特征检测与跟踪
MIN_FEATURES_TO_TRACK = 30
FEATURE_QUALITY = 0.01
FEATURE_MIN_DISTANCE = 10
LUCAS_KANADE_WINDOW = 15
LUCAS_KANADE_LEVELS = 2

# RANSAC / 变换估计
RANSAC_THRESHOLD = 3.0
MIN_INLIER_RATIO = 0.25
MIN_TRACKED_FEATURES = 8

# 帧对有效性
MAX_SINGLE_PAIR_SCALE = 1.5
MAX_SINGLE_PAIR_ROTATION_DEG = 15.0
MAX_SINGLE_PAIR_TRANSLATION_RATIO = 0.35

# Shot 级别
MIN_VALID_PAIR_RATIO = 0.4
MIN_VALID_PAIRS_ABSOLUTE = 2

# 运动强度分类（基于累计变化幅度）
STRENGTH_THRESHOLDS = {
    "none": 0.005,
    "very_light": 0.02,
    "light": 0.05,
    "medium": 0.15,
    "strong": float("inf"),
}

# Confidence 加权
CONFIDENCE_WEIGHTS = {
    "inlier_ratio": 0.30,
    "tracked_features": 0.20,
    "valid_pair_ratio": 0.30,
    "stability": 0.20,
}

# Shake heuristic
SHAKE_DIRECTION_FLIPS = 0.4
SHAKE_ROTATION_FLIPS = 0.3
SHAKE_AMPLITUDE_PX = 2.0

# Motion Fusion 阈值
FUSION_SCALE_THRESHOLD_PERCENT = 1.0
FUSION_TRANSLATION_THRESHOLD_RATIO = 0.01
FUSION_ROTATION_THRESHOLD_DEG = 1.0
FUSION_SHAKE_THRESHOLD = 0.5
